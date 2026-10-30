// Optional S3 offload: finished recording chunks move to S3_BUCKET under the same relative path.
import { createReadStream } from 'node:fs';
import { rm, stat } from 'node:fs/promises';
import path from 'node:path';
import {
  DeleteObjectCommand,
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { config } from '../config.js';
import { pool } from '../db.js';

const EVERY_MS = 5 * 60 * 1000;
const SETTLE_MIN = 2; // a chunk must have ended this long ago (clips may still be cut from it)
const root = path.resolve(config.STORAGE_DIR);

export const s3Enabled = () => Boolean(config.S3_BUCKET);

let client = null;
const s3 = () =>
  (client ??= new S3Client({
    region: config.S3_REGION,
    endpoint: config.S3_ENDPOINT || undefined,
    forcePathStyle: Boolean(config.S3_ENDPOINT),
  }));
const key = (rel) => `${config.S3_PREFIX}${rel}`;

export async function uploadFile(rel) {
  const full = path.resolve(root, rel);
  if (!full.startsWith(root + path.sep)) throw new Error(`bad path ${rel}`);
  const { size } = await stat(full);
  await s3().send(
    new PutObjectCommand({
      Bucket: config.S3_BUCKET,
      Key: key(rel),
      Body: createReadStream(full),
      ContentLength: size,
      ContentType: 'video/mp4',
    }),
  );
  // Only drop the local copy once S3 has the whole file.
  const head = await s3().send(new HeadObjectCommand({ Bucket: config.S3_BUCKET, Key: key(rel) }));
  if (head.ContentLength !== size) throw new Error(`size mismatch for ${rel}: ${head.ContentLength} != ${size}`);
  await rm(full, { force: true });
}

export async function deleteObject(rel) {
  await s3().send(new DeleteObjectCommand({ Bucket: config.S3_BUCKET, Key: key(rel) }));
}

export function signedUrl(rel, seconds = 300) {
  return getSignedUrl(s3(), new GetObjectCommand({ Bucket: config.S3_BUCKET, Key: key(rel) }), { expiresIn: seconds });
}

export async function offloadChunks() {
  const [rows] = await pool.query(
    `SELECT id, path FROM recordings
     WHERE in_s3 = FALSE AND ended_at IS NOT NULL AND ended_at < UTC_TIMESTAMP() - INTERVAL ? MINUTE
     ORDER BY id LIMIT 200`,
    [SETTLE_MIN],
  );
  let moved = 0;
  for (const r of rows) {
    try {
      await uploadFile(r.path);
      await pool.query('UPDATE recordings SET in_s3 = TRUE WHERE id = ?', [r.id]);
      moved++;
    } catch (err) {
      console.error(`offload ${r.path} failed:`, err.message); // retried next run; local file untouched
    }
  }
  return moved;
}

export function startOffload() {
  if (!s3Enabled()) return;
  const run = () =>
    offloadChunks()
      .then((n) => n && console.log(`s3: offloaded ${n} chunks`))
      .catch((err) => console.error('s3 offload failed:', err.message));
  setTimeout(run, 30_000);
  setInterval(run, EVERY_MS);
}
