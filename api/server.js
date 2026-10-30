import { createServer } from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import cookieParser from 'cookie-parser';
import { config } from './config.js';
import { camRouter } from './routes/cam.js';
import { internalRouter } from './routes/internal.js';
import { startStaleChecker } from './lib/stale.js';
import { startRetention } from './lib/retention.js';
import { startOffload } from './lib/s3.js';
import { callback, dashboardEnabled, login, logout } from './lib/adminAuth.js';
import { startLive } from './lib/live.js';
import { adminRouter } from './routes/admin.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const app = express();

app.set('trust proxy', 1); // behind Nginx
app.disable('x-powered-by');
app.use(express.json({ limit: '16kb' }));
app.use(cookieParser());

app.get('/healthz', (_req, res) => res.json({ ok: true }));
app.get('/api/brand', (_req, res) => {
  res.set('cache-control', 'public, max-age=300');
  res.json({
    name: config.BRAND_NAME,
    tagline: config.BRAND_TAGLINE,
    accent: config.BRAND_ACCENT,
    logoUrl: config.BRAND_LOGO_URL || null,
    bgUrl: config.BRAND_BG_URL || null,
  });
});
app.use('/api/cam', camRouter);
app.use('/internal', internalRouter);
if (dashboardEnabled()) {
  app.get('/auth/login', login);
  app.get('/auth/callback', callback);
  app.get('/auth/logout', logout);
  app.use('/admin', adminRouter);
} else {
  console.warn('admin dashboard off: set DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET and SESSION_SECRET');
}

app.get('/vendor/livekit-client.umd.js', (_req, res) =>
  res.sendFile(path.join(root, 'node_modules/livekit-client/dist/livekit-client.umd.js')),
);
app.use('/vendor/fonts/outfit', express.static(path.join(root, 'node_modules/@fontsource/outfit'), { maxAge: '30d' }));
app.use('/vendor/fonts/inter', express.static(path.join(root, 'node_modules/@fontsource-variable/inter'), { maxAge: '30d' }));
app.get('/vendor/socket.io.min.js', (_req, res) =>
  res.sendFile(path.join(root, 'node_modules/socket.io/client-dist/socket.io.min.js')),
);
app.use(express.static(path.join(root, 'web'), { extensions: ['html'] }));

// eslint-disable-next-line no-unused-vars
app.use((err, req, res, _next) => {
  // Log the route and error only; request bodies can carry cam tokens.
  console.error(`${req.method} ${req.path} failed:`, err.message);
  res.status(500).json({ error: 'Server error.' });
});

const server = createServer(app);
if (dashboardEnabled()) await startLive(server);
server.listen(config.PORT, '127.0.0.1', () => console.log(`api listening on :${config.PORT}`));
startStaleChecker();
startRetention();
startOffload();
