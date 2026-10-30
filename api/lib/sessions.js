// Session + cam link lifecycle. Shared by the API and (from Phase 3) the Discord bot.
import { pool } from '../db.js';
import { config } from '../config.js';
import { hashMatches, randomToken, sha256 } from './tokens.js';
import { closeRoom } from './livekit.js';
import { publish } from './bus.js';

export class CamLinkError extends Error {
  constructor(code) {
    super(code);
    this.code = code; // invalid | expired | used | ended
  }
}

export async function ensureGuild(discordGuildId) {
  const [res] = await pool.query(
    `INSERT INTO guilds (discord_guild_id) VALUES (?)
     ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)`,
    [discordGuildId],
  );
  return res.insertId;
}

// The token lives in the URL fragment so it never reaches server or proxy logs.
const camUrl = (token) => `${config.PUBLIC_URL}/cam.html#t=${token}`;

// Creates a pending session and returns its one-time cam link.
export async function createSession({ discordGuildId, discordUserId, playerName = null, matchLabel = null }) {
  const guildId = await ensureGuild(discordGuildId);
  const token = randomToken();
  const [res] = await pool.query(
    `INSERT INTO sessions (guild_id, discord_user_id, player_name, match_label, token_hash, token_expires_at)
     VALUES (?, ?, ?, ?, ?, UTC_TIMESTAMP(3) + INTERVAL ? MINUTE)`,
    [guildId, discordUserId, playerName, matchLabel, sha256(token), config.CAM_LINK_TTL_MIN],
  );
  return { sessionId: res.insertId, camUrl: camUrl(token) };
}

// New link for a session whose link was never opened (lost DM, expired link).
// Returns null once a device has claimed the session.
export async function reissueCamLink(sessionId) {
  const token = randomToken();
  const [res] = await pool.query(
    `UPDATE sessions SET token_hash = ?, token_expires_at = UTC_TIMESTAMP(3) + INTERVAL ? MINUTE
     WHERE id = ? AND token_used_at IS NULL AND status = 'pending'`,
    [sha256(token), config.CAM_LINK_TTL_MIN, sessionId],
  );
  return res.affectedRows ? camUrl(token) : null;
}

export const SESSION_COLUMNS = `s.id, s.status, s.match_label AS matchLabel, s.discord_user_id AS discordUserId,
  s.player_name AS playerName,
  g.discord_guild_id AS discordGuildId, s.token_used_at IS NOT NULL AS linkOpened,
  s.started_at AS startedAt, s.ended_at AS endedAt, s.uptime_sec AS uptimeSec,
  s.data_bytes AS dataBytes`;

// Latest session for a player that has not ended (pending, live or stale).
export async function activeSession(discordGuildId, discordUserId) {
  const [rows] = await pool.query(
    `SELECT ${SESSION_COLUMNS} FROM sessions s JOIN guilds g ON g.id = s.guild_id
     WHERE g.discord_guild_id = ? AND s.discord_user_id = ? AND s.status <> 'ended'
     ORDER BY s.id DESC LIMIT 1`,
    [discordGuildId, discordUserId],
  );
  return rows[0] ?? null;
}

export async function activeSessionsByMatch(discordGuildId, matchLabel) {
  const [rows] = await pool.query(
    `SELECT ${SESSION_COLUMNS} FROM sessions s JOIN guilds g ON g.id = s.guild_id
     WHERE g.discord_guild_id = ? AND s.match_label = ? AND s.status <> 'ended'`,
    [discordGuildId, matchLabel],
  );
  return rows;
}

// Unresolved warnings/violations decide the ✅ / ⚠️ / ❌ badge.
export async function sessionEventCounts(sessionId) {
  const [rows] = await pool.query(
    `SELECT
       SUM(severity = 'warning') AS warnings,
       SUM(severity = 'violation') AS violations,
       SUM(severity = 'warning' AND admin_action IS NULL) AS openWarnings,
       SUM(severity = 'violation' AND admin_action IS NULL) AS openViolations
     FROM events WHERE session_id = ?`,
    [sessionId],
  );
  const r = rows[0];
  return {
    warnings: Number(r.warnings ?? 0),
    violations: Number(r.violations ?? 0),
    openWarnings: Number(r.openWarnings ?? 0),
    openViolations: Number(r.openViolations ?? 0),
  };
}

// Ends the session and closes its LiveKit room, which disconnects the cam.
export async function endSession(session) {
  const [res] = await pool.query(
    `UPDATE sessions SET status = 'ended', ended_at = UTC_TIMESTAMP(3)
     WHERE id = ? AND status <> 'ended'`,
    [session.id],
  );
  if (!res.affectedRows) return false;
  await closeRoom(session.id);
  await publish({ type: 'ended', ...pick(session) });
  return true;
}

const pick = (s) => ({
  sessionId: s.id,
  discordGuildId: s.discordGuildId,
  discordUserId: s.discordUserId,
  matchLabel: s.matchLabel,
});

// First redeem binds the link to this device (returns a new device secret for a cookie).
// Later redeems (reloads, reconnects) must present that device secret.
export async function redeemCamLink(token, deviceSecret) {
  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();
    const [rows] = await conn.query(
      `SELECT s.id, s.status, s.match_label AS matchLabel, s.discord_user_id AS discordUserId,
              g.discord_guild_id AS discordGuildId, s.token_used_at, s.device_hash, s.started_at,
              s.token_expires_at < UTC_TIMESTAMP(3) AS expired
       FROM sessions s JOIN guilds g ON g.id = s.guild_id
       WHERE s.token_hash = ? FOR UPDATE`,
      [sha256(token)],
    );
    const s = rows[0];
    if (!s) throw new CamLinkError('invalid');
    if (s.status === 'ended') throw new CamLinkError('ended');

    let newDeviceSecret = null;
    if (!s.token_used_at) {
      if (s.expired) throw new CamLinkError('expired');
      newDeviceSecret = randomToken();
      await conn.query(
        `UPDATE sessions SET token_used_at = UTC_TIMESTAMP(3), device_hash = ?
         WHERE id = ?`,
        [sha256(newDeviceSecret), s.id],
      );
    } else if (!hashMatches(deviceSecret, s.device_hash)) {
      throw new CamLinkError('used');
    }

    await conn.query(
      `UPDATE sessions SET status = 'live', started_at = COALESCE(started_at, UTC_TIMESTAMP(3))
       WHERE id = ?`,
      [s.id],
    );
    await conn.commit();
    if (!s.started_at) await publish({ type: 'live', ...pick(s) });
    return { sessionId: s.id, matchLabel: s.matchLabel, newDeviceSecret };
  } catch (err) {
    await conn.rollback();
    throw err;
  } finally {
    conn.release();
  }
}

// Same device check as a repeat redeem, without side effects.
export async function authDevice(token, deviceSecret) {
  const [rows] = await pool.query(
    `SELECT id, status, device_hash FROM sessions WHERE token_hash = ?`,
    [sha256(token)],
  );
  const s = rows[0];
  if (!s || s.status === 'ended' || !hashMatches(deviceSecret, s.device_hash)) return null;
  return s.id;
}

// Read-only look at a cam link for the start screen: who it's for and whether it can still be used here.
// state: ready (unused) | resume (already bound to this device) | used | expired | ended | invalid
export async function peekCamLink(token, deviceSecrets) {
  const [rows] = await pool.query(
    `SELECT player_name AS playerName, match_label AS matchLabel, status, token_used_at AS usedAt,
            device_hash AS deviceHash, token_expires_at < UTC_TIMESTAMP(3) AS expired
     FROM sessions WHERE token_hash = ?`,
    [sha256(token)],
  );
  const s = rows[0];
  if (!s) return { state: 'invalid' };
  const info = { playerName: s.playerName, matchLabel: s.matchLabel };
  if (s.status === 'ended') return { state: 'ended', ...info };
  if (!s.usedAt) return { state: s.expired ? 'expired' : 'ready', ...info };
  const mine = deviceSecrets.some((secret) => hashMatches(secret, s.deviceHash));
  return { state: mine ? 'resume' : 'used', ...info };
}

export async function addDataUsed(sessionId, bytes) {
  await pool.query('UPDATE sessions SET data_bytes = data_bytes + ? WHERE id = ?', [bytes, sessionId]);
}
