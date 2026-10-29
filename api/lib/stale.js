// Marks live sessions STALE when the worker's heartbeat (every 10s) goes missing.
import { pool } from '../db.js';
import { publish } from './bus.js';

const STALE_AFTER_SEC = 30;
const CHECK_EVERY_MS = 10_000;

export async function markStaleSessions() {
  const [rows] = await pool.query(
    `SELECT s.id, s.match_label AS matchLabel, s.discord_user_id AS discordUserId,
            g.discord_guild_id AS discordGuildId
     FROM sessions s JOIN guilds g ON g.id = s.guild_id
     WHERE s.status = 'live'
       AND COALESCE(s.last_heartbeat_at, s.started_at) < UTC_TIMESTAMP(3) - INTERVAL ? SECOND`,
    [STALE_AFTER_SEC],
  );
  for (const { id, ...who } of rows) {
    const [res] = await pool.query(`UPDATE sessions SET status = 'stale' WHERE id = ? AND status = 'live'`, [id]);
    if (res.affectedRows) await publish({ type: 'stale', sessionId: id, ...who });
  }
}

export function startStaleChecker() {
  setInterval(() => markStaleSessions().catch((err) => console.error('stale check failed:', err.message)), CHECK_EVERY_MS);
}
