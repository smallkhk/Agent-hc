// Session + cam link lifecycle. Shared by the API and (from Phase 3) the Discord bot.
import { pool } from '../db.js';
import { config } from '../config.js';
import { hashMatches, randomToken, sha256 } from './tokens.js';

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

// Creates a pending session and returns its one-time cam link.
// The token lives in the URL fragment so it never reaches server or proxy logs.
export async function createSession({ discordGuildId, discordUserId, matchLabel = null }) {
  const guildId = await ensureGuild(discordGuildId);
  const token = randomToken();
  const [res] = await pool.query(
    `INSERT INTO sessions (guild_id, discord_user_id, match_label, token_hash, token_expires_at)
     VALUES (?, ?, ?, ?, UTC_TIMESTAMP(3) + INTERVAL ? MINUTE)`,
    [guildId, discordUserId, matchLabel, sha256(token), config.CAM_LINK_TTL_MIN],
  );
  return { sessionId: res.insertId, camUrl: `${config.PUBLIC_URL}/cam.html#t=${token}` };
}

// First redeem binds the link to this device (returns a new device secret for a cookie).
// Later redeems (reloads, reconnects) must present that device secret.
export async function redeemCamLink(token, deviceSecret) {
  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();
    const [rows] = await conn.query(
      `SELECT id, status, match_label, token_used_at, device_hash,
              token_expires_at < UTC_TIMESTAMP(3) AS expired
       FROM sessions WHERE token_hash = ? FOR UPDATE`,
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
    return { sessionId: s.id, matchLabel: s.match_label, newDeviceSecret };
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

export async function addDataUsed(sessionId, bytes) {
  await pool.query('UPDATE sessions SET data_bytes = data_bytes + ? WHERE id = ?', [bytes, sessionId]);
}
