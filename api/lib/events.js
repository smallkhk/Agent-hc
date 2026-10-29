// Alert events: lookup for the Discord alert, and admin resolution (saved as training labels).
import { pool } from '../db.js';

export async function getEvent(eventId) {
  const [rows] = await pool.query(
    `SELECT e.id, e.type, e.severity, e.score, e.ts, e.frame_path AS framePath, e.clip_path AS clipPath,
            e.admin_action AS adminAction, e.admin_id AS adminId,
            s.id AS sessionId, s.discord_user_id AS discordUserId, s.match_label AS matchLabel,
            g.discord_guild_id AS discordGuildId
     FROM events e JOIN sessions s ON s.id = e.session_id JOIN guilds g ON g.id = s.guild_id
     WHERE e.id = ?`,
    [eventId],
  );
  return rows[0] ?? null;
}

// First admin to click wins. Returns false if the event was already resolved.
export async function resolveEvent(eventId, action, adminId) {
  const conn = await pool.getConnection();
  try {
    await conn.beginTransaction();
    const [res] = await conn.query(
      `UPDATE events SET admin_action = ?, admin_id = ?, resolved_at = UTC_TIMESTAMP(3)
       WHERE id = ? AND admin_action IS NULL`,
      [action, adminId, eventId],
    );
    if (!res.affectedRows) {
      await conn.rollback();
      return false;
    }
    // Label = the rule for a confirmed flag, 'false_positive' otherwise (event_id keeps the rule).
    if (action !== 'ignored') {
      await conn.query(
        `INSERT INTO training_samples (event_id, image_path, label, source)
         SELECT id, frame_path, IF(? = 'confirmed', type, 'false_positive'), 'admin'
         FROM events WHERE id = ? AND frame_path IS NOT NULL`,
        [action, eventId],
      );
    }
    await conn.commit();
    return true;
  } catch (err) {
    await conn.rollback();
    throw err;
  } finally {
    conn.release();
  }
}
