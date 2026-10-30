// Admin dashboard API. Every route is limited to the servers the logged-in admin manages.
import path from 'node:path';
import { Router } from 'express';
import { z } from 'zod';
import { config } from '../config.js';
import { pool } from '../db.js';
import { requireAdmin } from '../lib/adminAuth.js';
import { watchToken } from '../lib/livekit.js';
import { resolveAlert } from '../lib/resolve.js';
import { s3Enabled, signedUrl } from '../lib/s3.js';
import { endSession, SESSION_COLUMNS } from '../lib/sessions.js';

export const adminRouter = Router();
adminRouter.use(requireAdmin);

const storageRoot = path.resolve(config.STORAGE_DIR);

async function sessionFor(req, id) {
  const [rows] = await pool.query(
    `SELECT ${SESSION_COLUMNS} FROM sessions s JOIN guilds g ON g.id = s.guild_id WHERE s.id = ?`,
    [id],
  );
  const s = rows[0];
  return s && req.adminGuilds.has(s.discordGuildId) ? s : null;
}

const idParam = (req) => {
  const id = Number(req.params.id);
  return Number.isInteger(id) && id > 0 ? id : null;
};

adminRouter.get('/api/me', (req, res) => {
  res.json({ id: req.admin.uid, name: req.admin.name, guilds: req.admin.guilds });
});

// Live/pending/stale sessions plus the last 24 h of ended ones, with alert counts for the badges.
adminRouter.get('/api/sessions', async (req, res, next) => {
  const guild = String(req.query.guild ?? '');
  if (!req.adminGuilds.has(guild)) return res.status(403).json({ error: 'Forbidden.' });
  try {
    const [rows] = await pool.query(
      `SELECT ${SESSION_COLUMNS},
         (SELECT COUNT(*) FROM events e WHERE e.session_id = s.id AND e.severity = 'warning' AND e.admin_action IS NULL) AS openWarnings,
         (SELECT COUNT(*) FROM events e WHERE e.session_id = s.id AND e.severity = 'violation' AND e.admin_action IS NULL) AS openViolations,
         (SELECT COUNT(*) FROM events e WHERE e.session_id = s.id AND e.severity <> 'info') AS alerts
       FROM sessions s JOIN guilds g ON g.id = s.guild_id
       WHERE g.discord_guild_id = ?
         AND (s.status <> 'ended' OR s.ended_at > UTC_TIMESTAMP() - INTERVAL 1 DAY)
       ORDER BY s.status = 'ended', s.id DESC
       LIMIT 200`,
      [guild],
    );
    res.json({ sessions: rows });
  } catch (err) {
    next(err);
  }
});

adminRouter.get('/api/sessions/:id', async (req, res, next) => {
  try {
    const s = await sessionFor(req, idParam(req));
    if (!s) return res.status(404).json({ error: 'Not found.' });
    const [events] = await pool.query(
      `SELECT id, type, severity, score, ts, frame_path AS framePath, clip_path AS clipPath,
              admin_action AS adminAction, admin_id AS adminId, resolved_at AS resolvedAt, llm_verdict AS llmVerdict
       FROM events WHERE session_id = ? ORDER BY ts DESC LIMIT 500`,
      [s.id],
    );
    const [recordings] = await pool.query(
      `SELECT id, path, started_at AS startedAt, ended_at AS endedAt, size_bytes AS sizeBytes, keep
       FROM recordings WHERE session_id = ? ORDER BY started_at`,
      [s.id],
    );
    res.json({ session: s, events, recordings });
  } catch (err) {
    next(err);
  }
});

adminRouter.post('/api/sessions/:id/watch', async (req, res, next) => {
  try {
    const s = await sessionFor(req, idParam(req));
    if (!s) return res.status(404).json({ error: 'Not found.' });
    res.json({ url: config.LIVEKIT_URL, token: await watchToken(s.id, `admin-${req.admin.uid}`) });
  } catch (err) {
    next(err);
  }
});

adminRouter.post('/api/sessions/:id/stop', async (req, res, next) => {
  try {
    const s = await sessionFor(req, idParam(req));
    if (!s) return res.status(404).json({ error: 'Not found.' });
    res.json({ ended: await endSession(s) });
  } catch (err) {
    next(err);
  }
});

const resolveBody = z.object({ action: z.enum(['confirm', 'fp', 'ignore']) });

adminRouter.post('/api/events/:id/resolve', async (req, res, next) => {
  const body = resolveBody.safeParse(req.body);
  const eventId = idParam(req);
  if (!body.success || !eventId) return res.status(400).json({ error: 'Bad request.' });
  try {
    const [rows] = await pool.query('SELECT session_id AS sessionId FROM events WHERE id = ?', [eventId]);
    if (!rows[0] || !(await sessionFor(req, rows[0].sessionId))) return res.status(404).json({ error: 'Not found.' });
    const { ok, event } = await resolveAlert(eventId, body.data.action, req.admin.uid, { source: 'dashboard' });
    res.status(ok ? 200 : 409).json({ ok, adminAction: event.adminAction, adminId: event.adminId });
  } catch (err) {
    next(err);
  }
});

// Latest frame the worker saw (written every sample).
adminRouter.get('/api/sessions/:id/thumb.jpg', async (req, res, next) => {
  try {
    const s = await sessionFor(req, idParam(req));
    if (!s) return res.status(404).end();
    res.set('cache-control', 'no-store');
    res.sendFile(path.join(storageRoot, 'thumbs', `${s.id}.jpg`), (err) => err && !res.headersSent && res.status(404).end());
  } catch (err) {
    next(err);
  }
});

// Snapshots, clips and recording chunks: /admin/media/<frames|clips|recordings>/<session>/<file>
adminRouter.get(/^\/media\/(frames|clips|recordings)\/(\d+)\/([\w.-]+\.(?:jpg|mp4))$/, async (req, res, next) => {
  try {
    const [kind, sid, file] = [req.params[0], Number(req.params[1]), req.params[2]];
    if (!(await sessionFor(req, sid))) return res.status(404).end();
    if (kind === 'recordings' && s3Enabled()) {
      const rel = `recordings/${sid}/${file}`;
      const [[rec]] = await pool.query('SELECT in_s3 AS inS3 FROM recordings WHERE path = ?', [rel]);
      if (rec?.inS3) return res.redirect(await signedUrl(rel)); // short-lived link straight to S3
    }
    const full = path.resolve(storageRoot, kind, String(sid), file);
    if (!full.startsWith(storageRoot + path.sep)) return res.status(404).end();
    res.sendFile(full, { dotfiles: 'deny' }, (err) => err && !res.headersSent && res.status(404).end()); // Range-capable
  } catch (err) {
    next(err);
  }
});
