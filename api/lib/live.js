// Socket.IO push for the dashboard: session and event changes, per guild room.
import { parse as parseCookies } from 'cookie';
import { Server } from 'socket.io';
import { pool } from '../db.js';
import { COOKIE, decodeSession } from './adminAuth.js';
import { CLIPS_CHANNEL, DASHBOARD_CHANNEL, SESSIONS_CHANNEL, subscribe } from './bus.js';
import { RESOLVED_CHANNEL } from './resolve.js';

async function guildOfEvent(eventId) {
  const [rows] = await pool.query(
    `SELECT e.session_id AS sessionId, g.discord_guild_id AS guildId
     FROM events e JOIN sessions s ON s.id = e.session_id JOIN guilds g ON g.id = s.guild_id WHERE e.id = ?`,
    [eventId],
  );
  return rows[0] ?? null;
}

export async function startLive(httpServer) {
  const io = new Server(httpServer, { path: '/admin/socket', serveClient: false });

  io.use((socket, next) => {
    const session = decodeSession(parseCookies(socket.request.headers.cookie ?? '')[COOKIE]);
    if (!session) return next(new Error('unauthorized'));
    socket.data.session = session;
    next();
  });
  io.on('connection', (socket) => {
    for (const g of socket.data.session.guilds) socket.join(`guild:${g.id}`);
  });

  await subscribe(SESSIONS_CHANNEL, (m) => {
    if (m.discordGuildId) io.to(`guild:${m.discordGuildId}`).emit('session', { type: m.type, sessionId: m.sessionId });
  });
  const forEvent = (kind) => async (m) => {
    const where = await guildOfEvent(m.eventId).catch(() => null);
    if (where) io.to(`guild:${where.guildId}`).emit('event', { kind, eventId: m.eventId, sessionId: where.sessionId });
  };
  await subscribe(DASHBOARD_CHANNEL, forEvent('new'));
  await subscribe(CLIPS_CHANNEL, forEvent('clip'));
  await subscribe(RESOLVED_CHANNEL, forEvent('resolved'));
  return io;
}
