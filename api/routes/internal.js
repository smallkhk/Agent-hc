// Endpoints for the vision worker (same host). Bearer WORKER_SECRET.
import { Router } from 'express';
import { z } from 'zod';
import { config } from '../config.js';
import { pool } from '../db.js';
import { CLIPS_CHANNEL, DASHBOARD_CHANNEL, EVENTS_CHANNEL, isMuted, publish } from '../lib/bus.js';
import { getGuildConfig } from '../lib/guildConfig.js';
import { roomName } from '../lib/livekit.js';
import { hashMatches, sha256 } from '../lib/tokens.js';

export const internalRouter = Router();

const secretHash = sha256(config.WORKER_SECRET);
internalRouter.use((req, res, next) => {
  const token = req.get('authorization')?.replace(/^Bearer /, '');
  if (!hashMatches(token, secretHash)) return res.status(401).json({ error: 'Unauthorized.' });
  next();
});

// Sessions the worker should watch, with each guild's thresholds.
internalRouter.get('/sessions', async (_req, res, next) => {
  try {
    const [rows] = await pool.query(
      `SELECT s.id, g.discord_guild_id AS guildId FROM sessions s JOIN guilds g ON g.id = s.guild_id
       WHERE s.status IN ('live', 'stale')`,
    );
    const configs = new Map();
    for (const guildId of new Set(rows.map((r) => r.guildId))) configs.set(guildId, await getGuildConfig(guildId));
    res.json({
      sessions: rows.map((r) => {
        const c = configs.get(r.guildId);
        return {
          id: r.id,
          room: roomName(r.id),
          thresholds: {
            graceSec: c.graceSec,
            violationSec: c.violationSec,
            freezeSec: c.freezeSec,
            dropSec: c.dropSec,
            menuThreshold: c.menuThreshold,
          },
        };
      }),
    });
  } catch (err) {
    next(err);
  }
});

const heartbeatBody = z.object({
  sessions: z
    .array(
      z.object({
        id: z.number().int().positive(),
        connected: z.boolean(),
        uptimeDeltaSec: z.number().min(0).max(120),
        chunks: z
          .array(
            z.object({
              path: z.string().regex(/^recordings\/\d+\/\d{8}T\d{6}Z\.mp4$/),
              startedAt: z.number().int().positive(),
              endedAt: z.number().int().positive(),
              sizeBytes: z.number().int().nonnegative(),
              active: z.boolean(),
            }),
          )
          .max(1000)
          .default([]),
      }),
    )
    .max(500),
});

internalRouter.post('/heartbeat', async (req, res, next) => {
  const body = heartbeatBody.safeParse(req.body);
  if (!body.success) return res.status(400).json({ error: 'Bad request.' });
  try {
    for (const s of body.data.sessions) {
      const [rows] = await pool.query(
        `SELECT s.status, s.match_label AS matchLabel, s.discord_user_id AS discordUserId,
                g.discord_guild_id AS discordGuildId
         FROM sessions s JOIN guilds g ON g.id = s.guild_id WHERE s.id = ?`,
        [s.id],
      );
      const { status, ...who } = rows[0] ?? {};
      if (!status) continue;
      // Chunks are recorded even after the session ended (the worker's final report).
      for (const c of s.chunks) {
        if (!c.path.startsWith(`recordings/${s.id}/`)) continue;
        await pool.query(
          `INSERT INTO recordings (session_id, path, started_at, ended_at, size_bytes)
           VALUES (?, ?, FROM_UNIXTIME(? / 1000), ?, ?)
           ON DUPLICATE KEY UPDATE ended_at = VALUES(ended_at), size_bytes = VALUES(size_bytes)`,
          [s.id, c.path, c.startedAt, c.active ? null : new Date(c.endedAt), c.sizeBytes],
        );
      }
      if (status !== 'live' && status !== 'stale') continue;
      await pool.query(
        `UPDATE sessions SET last_heartbeat_at = UTC_TIMESTAMP(3), uptime_sec = uptime_sec + ?, status = 'live'
         WHERE id = ? AND status IN ('live', 'stale')`,
        [Math.round(s.uptimeDeltaSec), s.id],
      );
      if (status === 'stale') await publish({ type: 'recovered', sessionId: s.id, ...who });
    }
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});

const eventBody = z.object({
  sessionId: z.number().int().positive(),
  type: z.string().regex(/^[A-Za-z_]{2,32}$/),
  severity: z.enum(['info', 'warning', 'violation']),
  score: z.number().nullable().optional(),
  ts: z.number().int().positive(),
  framePath: z
    .string()
    .regex(/^frames\/\d+\/[\w.-]+\.jpg$/)
    .nullable()
    .optional(),
});

internalRouter.post('/events', async (req, res, next) => {
  const body = eventBody.safeParse(req.body);
  if (!body.success) return res.status(400).json({ error: 'Bad request.' });
  const e = body.data;
  try {
    const [rows] = await pool.query('SELECT status FROM sessions WHERE id = ?', [e.sessionId]);
    if (!rows[0] || rows[0].status === 'ended') return res.status(409).json({ error: 'Session not active.' });

    const alert = e.severity !== 'info';
    const muted = alert && (await isMuted(e.sessionId, e.type));
    const [ins] = await pool.query(
      `INSERT INTO events (session_id, type, severity, score, ts, frame_path, admin_action)
       VALUES (?, ?, ?, ?, FROM_UNIXTIME(? / 1000), ?, ?)`,
      [e.sessionId, e.type, e.severity, e.score ?? null, e.ts, e.framePath ?? null, muted ? 'ignored' : null],
    );
    if (alert && !muted) await publish({ eventId: ins.insertId }, EVENTS_CHANNEL);
    await publish({ eventId: ins.insertId }, DASHBOARD_CHANNEL);
    res.status(201).json({ id: ins.insertId, muted });
  } catch (err) {
    next(err);
  }
});

const clipBody = z.object({ clipPath: z.string().regex(/^clips\/\d+\/[\w.-]+\.mp4$/) });

internalRouter.post('/events/:id/clip', async (req, res, next) => {
  const eventId = Number(req.params.id);
  const body = clipBody.safeParse(req.body);
  if (!Number.isInteger(eventId) || !body.success) return res.status(400).json({ error: 'Bad request.' });
  try {
    const [r] = await pool.query(
      `UPDATE events e SET e.clip_path = ?
       WHERE e.id = ? AND ? LIKE CONCAT('clips/', e.session_id, '/%')`,
      [body.data.clipPath, eventId, body.data.clipPath],
    );
    if (!r.affectedRows) return res.status(404).json({ error: 'Unknown event.' });
    await publish({ eventId }, CLIPS_CHANNEL);
    res.status(204).end();
  } catch (err) {
    next(err);
  }
});
