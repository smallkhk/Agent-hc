// Storage retention (hourly):
// - recording chunks: deleted after RETENTION_DAYS unless they overlap an unresolved warning/violation
// - clips and snapshots: deleted after RETENTION_DAYS once resolved as false positive / ignored
//   (or for info events); confirmed events keep them as evidence, and snapshots used as
//   training samples are kept
import path from 'node:path';
import { rm } from 'node:fs/promises';
import { config } from '../config.js';
import { pool } from '../db.js';
import { deleteObject } from './s3.js';

const EVERY_MS = 60 * 60 * 1000;
const root = path.resolve(config.STORAGE_DIR);

async function removeFile(rel) {
  const full = path.resolve(root, rel);
  if (!full.startsWith(root + path.sep)) return; // never outside the storage dir
  await rm(full, { force: true });
}

// An unresolved flag within 15 s of a chunk pins it (the clip window reaches 10 s either side).
const UNRESOLVED_FLAG = `EXISTS (
  SELECT 1 FROM events e
  WHERE e.session_id = r.session_id AND e.severity IN ('warning', 'violation') AND e.admin_action IS NULL
    AND e.ts BETWEEN r.started_at - INTERVAL 15 SECOND AND COALESCE(r.ended_at, UTC_TIMESTAMP()) + INTERVAL 15 SECOND)`;

export async function runRetention(days = config.RETENTION_DAYS) {
  await pool.query(`UPDATE recordings r SET keep = ${UNRESOLVED_FLAG}`);

  const [chunks] = await pool.query(
    `SELECT id, path, in_s3 AS inS3 FROM recordings r
     WHERE keep = FALSE AND ended_at IS NOT NULL AND ended_at < UTC_TIMESTAMP() - INTERVAL ? DAY`,
    [days],
  );
  for (const c of chunks) {
    if (c.inS3) await deleteObject(c.path);
    await removeFile(c.path);
    await pool.query('DELETE FROM recordings WHERE id = ?', [c.id]);
  }

  const [media] = await pool.query(
    `SELECT e.id, e.clip_path AS clipPath, e.frame_path AS framePath,
            EXISTS (SELECT 1 FROM training_samples t WHERE t.event_id = e.id) AS isTraining
     FROM events e
     WHERE e.ts < UTC_TIMESTAMP() - INTERVAL ? DAY
       AND (e.clip_path IS NOT NULL OR e.frame_path IS NOT NULL)
       AND (e.admin_action IN ('false_positive', 'ignored') OR e.severity = 'info')`,
    [days],
  );
  let files = 0;
  for (const m of media) {
    for (const rel of [m.clipPath, m.isTraining ? null : m.framePath]) {
      if (!rel) continue;
      await removeFile(rel);
      files++;
    }
    await pool.query(
      `UPDATE events SET clip_path = NULL, frame_path = IF(?, frame_path, NULL) WHERE id = ?`,
      [m.isTraining, m.id],
    );
  }
  return { chunks: chunks.length, mediaFiles: files };
}

export function startRetention() {
  const run = () =>
    runRetention()
      .then((r) => (r.chunks || r.mediaFiles) && console.log(`retention: removed ${r.chunks} chunks, ${r.mediaFiles} files`))
      .catch((err) => console.error('retention failed:', err.message));
  setTimeout(run, 60_000);
  setInterval(run, EVERY_MS);
}
