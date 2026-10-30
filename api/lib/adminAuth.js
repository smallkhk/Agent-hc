// Admin dashboard login: Discord OAuth2 (identify + guilds) and an HMAC-signed session cookie.
// Admin of a server = Manage Server / Administrator there, or the role set with /handcam config admin_role.
import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { config } from '../config.js';
import { pool } from '../db.js';
import { getGuildConfig } from './guildConfig.js';

export const COOKIE = 'hc_admin';
const STATE_COOKIE = 'hc_oauth_state';
const TTL_MS = 12 * 60 * 60 * 1000;
const MANAGE_GUILD = 1n << 5n;
const ADMINISTRATOR = 1n << 3n;

export const dashboardEnabled = () =>
  Boolean(config.DISCORD_CLIENT_ID && config.DISCORD_CLIENT_SECRET && config.SESSION_SECRET);

const redirectUri = () => `${config.PUBLIC_URL}/auth/callback`;
const authorizeUrl = () => `${config.DISCORD_API_URL.replace(/\/api(\/v\d+)?$/, '')}/oauth2/authorize`;
const cookieOpts = (maxAge) => ({
  httpOnly: true,
  secure: config.secureCookies,
  sameSite: 'lax', // the OAuth redirect back from Discord is a top-level cross-site GET
  path: '/',
  maxAge,
});

const sign = (payload) => createHmac('sha256', config.SESSION_SECRET).update(payload).digest('base64url');

export function encodeSession(data) {
  const payload = Buffer.from(JSON.stringify({ ...data, exp: Date.now() + TTL_MS })).toString('base64url');
  return `${payload}.${sign(payload)}`;
}

export function decodeSession(cookie) {
  if (!cookie || !config.SESSION_SECRET) return null;
  const [payload, sig] = cookie.split('.');
  if (!payload || !sig) return null;
  const expected = Buffer.from(sign(payload));
  const given = Buffer.from(sig);
  if (expected.length !== given.length || !timingSafeEqual(expected, given)) return null;
  const data = JSON.parse(Buffer.from(payload, 'base64url').toString());
  return data.exp > Date.now() ? data : null;
}

async function discord(path, { token, bot = false, ...init } = {}) {
  const res = await fetch(`${config.DISCORD_API_URL}${path}`, {
    ...init,
    headers: { authorization: `${bot ? 'Bot' : 'Bearer'} ${token}`, ...init.headers },
  });
  if (!res.ok) {
    const err = new Error(`Discord ${path.split('?')[0]} → ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function hasAdminRole(guildId, userId, roleId) {
  if (!roleId || !config.DISCORD_TOKEN) return false;
  try {
    const member = await discord(`/guilds/${guildId}/members/${userId}`, { token: config.DISCORD_TOKEN, bot: true });
    return member.roles.includes(roleId);
  } catch {
    return false; // bot not in that server / member left
  }
}

// GET /auth/login
export function login(_req, res) {
  const state = randomBytes(16).toString('base64url');
  res.cookie(STATE_COOKIE, state, cookieOpts(10 * 60 * 1000));
  const q = new URLSearchParams({
    client_id: config.DISCORD_CLIENT_ID,
    redirect_uri: redirectUri(),
    response_type: 'code',
    scope: 'identify guilds',
    state,
    prompt: 'none',
  });
  res.redirect(`${authorizeUrl()}?${q}`);
}

// GET /auth/callback?code&state
export async function callback(req, res, next) {
  try {
    const { code, state } = req.query;
    if (typeof code !== 'string' || !state || state !== req.cookies[STATE_COOKIE]) {
      return res.status(400).send('Login failed (state mismatch). <a href="/auth/login">Try again</a>');
    }
    res.clearCookie(STATE_COOKIE, { path: '/' });
    const tokenRes = await fetch(`${config.DISCORD_API_URL}/oauth2/token`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: config.DISCORD_CLIENT_ID,
        client_secret: config.DISCORD_CLIENT_SECRET,
        grant_type: 'authorization_code',
        code,
        redirect_uri: redirectUri(),
      }),
    });
    if (!tokenRes.ok) return res.status(401).send('Discord login failed. <a href="/auth/login">Try again</a>');
    const { access_token: token } = await tokenRes.json();
    const [user, userGuilds] = await Promise.all([discord('/users/@me', { token }), discord('/users/@me/guilds', { token })]);

    // Only servers that use the hand cam bot.
    const [known] = await pool.query('SELECT discord_guild_id AS id FROM guilds');
    const knownIds = new Set(known.map((g) => g.id));
    const guilds = [];
    for (const g of userGuilds.filter((g) => knownIds.has(g.id))) {
      const perms = BigInt(g.permissions ?? 0);
      const byPermission = g.owner || (perms & (MANAGE_GUILD | ADMINISTRATOR)) !== 0n;
      if (byPermission || (await hasAdminRole(g.id, user.id, (await getGuildConfig(g.id)).adminRoleId))) {
        guilds.push({ id: g.id, name: g.name });
      }
    }
    if (!guilds.length) {
      return res.status(403).send('You are not a hand cam admin in any server. <a href="/">Back</a>');
    }
    res.cookie(COOKIE, encodeSession({ uid: user.id, name: user.global_name ?? user.username, guilds }), cookieOpts(TTL_MS));
    res.redirect('/admin.html');
  } catch (err) {
    next(err);
  }
}

export function logout(_req, res) {
  res.clearCookie(COOKIE, { path: '/' });
  res.redirect('/admin.html');
}

// Express middleware for /admin/api and /admin/media. POSTs also need a custom header (CSRF).
export function requireAdmin(req, res, next) {
  const session = decodeSession(req.cookies[COOKIE]);
  if (!session) return res.status(401).json({ error: 'Not logged in.' });
  if (req.method !== 'GET' && req.get('x-handcam') !== '1') return res.status(403).json({ error: 'Forbidden.' });
  req.admin = session;
  req.adminGuilds = new Set(session.guilds.map((g) => g.id));
  next();
}
