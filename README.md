# CODM Hand Cam Agent

AI-assisted hand cam monitoring for Call of Duty: Mobile lobbies, run through Discord. Full spec: [CLAUDE.md](CLAUDE.md).

Discord bots can't watch voice-channel video, so players open a one-time cam link (sent by the bot) on a second device.
That page streams through LiveKit Cloud to your server, where admins watch and the vision worker analyses the feed.
Players only use a browser: nothing to install.

## Setup

1. **Server:** Ubuntu with Docker, Node 20.12+, Python 3.11, FFmpeg, MySQL 8, Nginx. Only ports 80/443 need to be open.
   **LiveKit Cloud:** sign up at [cloud.livekit.io](https://cloud.livekit.io), create a project, and copy its URL, API key and
   secret into `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`. The free plan (5,000 minutes, 50 GB a month)
   covers about 80 one-player or 40 two-player 30-minute matches.
2. `cp .env.example .env` and fill it in (`WORKER_SECRET`: `openssl rand -hex 32`). `npm ci`, then `npm run db:migrate`.
   Vision worker: `python3.11 -m venv .venv && .venv/bin/pip install -r worker/requirements.txt`.
3. `cd deploy && docker compose --env-file ../.env up -d` (Redis). Running your own LiveKit server instead of the
   cloud: add `--profile selfhosted`, use `deploy/nginx/livekit-selfhosted.conf`, and open UDP 50000–60000 + TCP 7881.
4. Nginx: copy `deploy/nginx/handcam.conf`, replace the domains, run certbot.
5. **Discord app** ([Developer Portal](https://discord.com/developers/applications)):
   - Bot tab: copy the token into `DISCORD_TOKEN`. Application ID → `DISCORD_CLIENT_ID`.
   - Invite with scopes `bot` + `applications.commands` and permissions View Channels, Send Messages, Embed Links.
   - Role-based lobbies (`/handcam lobby start role:`) need **Server Members Intent** turned on, plus `DISCORD_MEMBERS_INTENT=true`.
     Voice-channel lobbies work without it.
6. `npm run bot:deploy` registers `/handcam` (set `DISCORD_DEV_GUILD_ID` to register to one server instantly while testing).
7. `pm2 start deploy/ecosystem.config.cjs`
8. In Discord: `/handcam config alert_channel:#handcam-alerts`.

## Branding

Players and admins see your name, colour and logo, not "HANDCAM". In `.env`:
`BRAND_NAME` (e.g. `FM Esports`), `BRAND_TAGLINE`, `BRAND_ACCENT` (hex colour, e.g. `#E5193B`; button text switches
to white or black automatically), and `BRAND_LOGO_URL` (put the file in `web/brand/`, then `/brand/logo.png`).
Restart the API to apply.

## Using it

| Command | Who | |
|---|---|---|
| `/handcam start @player [match]` | Admin | DMs the player a cam link (or a fresh one if they never opened it) |
| `/handcam lobby start [channel/role] [match]` | Admin | Same for everyone in a voice channel (default: the one you're in) or role |
| `/handcam join` | Player | Gets your cam link privately; works when DMs are closed. Self-start without an admin can be turned off with `self_join` |
| `/handcam status [@player]` | Anyone | ✅ OK / ⚠️ Warning / ❌ Violation, time live, data used |
| `/handcam stop @player`, `/handcam lobby stop` | Admin | Ends sessions and disconnects the cam |
| `/handcam config` | Admin | Alert channel, admin role, self join, rule thresholds. No options shows current settings |

Admins are members with **Manage Server**, or the role set with `/handcam config admin_role:`.

## Alerts

The vision worker checks every live cam twice a second and posts to the alert channel:

| Alert | When (defaults, change with `/handcam config`) |
|---|---|
| Screen partly out of frame / not visible / too small / too dark | warning after 10 s, violation after 30 s |
| Glare hides the screen | warning after 10 s |
| Camera feed frozen (or camera covered) | violation after 8 s |
| Hand cam disconnected | violation after 20 s |
| Feed looped / replayed (pre-recorded video) | violation when 20 consecutive samples (10 s) repeat an earlier part of the last 10 min |
| Camera scene changed (possible device swap) | warning |
| Mod menu / ESP / unknown overlay on screen | needs a trained model, see [training/README.md](training/README.md). Starts in shadow mode: logged, no alert, until `MENU_SHADOW=false` |

**AI second opinion (optional, off by default):** with `LLM_SECOND_OPINION=true`, each hack-menu flag also sends the
flattened screen to Claude (`LLM_MODEL`, default `claude-opus-5-5`, key in `LLM_API_KEY`; at most one request per
player every `LLM_MIN_INTERVAL_SEC`). Its verdict (e.g. `hack_menu (90%): toggle list with aimbot…`) is added to the
Discord alert and the dashboard. It only informs the admin; it never changes or removes an alert.

Each alert has the snapshot and **Confirm / False positive / Ignore 10m** buttons (admins only; first click wins).
Confirm and False positive are saved as training labels. The player's cam page shows what is wrong in the guide box.

## Recordings

Every session is recorded under `STORAGE_DIR/recordings/<session>/` in 10-minute MP4 chunks (H.264, stream resolution,
about 25–60 MB/hour at 480p). Chunks are written as they go, so a crash or restart loses only the last few seconds.
About 13 s after an alert, a 20 s clip (10 s before, 10 s after) is posted as a reply to the alert in Discord.

Retention runs hourly in the API:
- recording chunks are deleted after `RETENTION_DAYS` (7) unless they cover an alert nobody has resolved yet;
- clips and snapshots of false positives / ignored alerts are deleted after `RETENTION_DAYS`;
- clips and snapshots of **confirmed** alerts are kept, and so are snapshots saved as training samples.

**S3 offload (optional):** set `S3_BUCKET` (+ `S3_REGION`, AWS credentials or an instance role; `S3_ENDPOINT` for
MinIO / R2). Finished chunks are uploaded every 5 minutes, checked, then removed from local disk; the dashboard plays
them through 5-minute signed links and retention deletes them from S3. Clips and snapshots stay on local disk.

## Scaling

Each worker process handles many sessions (one asyncio task each). To use more cores, run several workers:
`WORKERS=3 pm2 start deploy/ecosystem.config.cjs` starts `handcam-worker-0..2`, and each takes the sessions whose
id % 3 matches its index. Measured on a 4-core test box: about 0.1 core per 854x480 session (decode, detection,
recording) at ~5–6 fps delivered; at a full 15 fps expect roughly 0.25 core per session, i.e. about 5 of 8 cores for
20 sessions. Check on your own hardware before a big event; `RECORD_FPS` and `SAMPLE_FPS` are the main knobs.

Worker tests (need `ffmpeg`): `.venv/bin/pip install pytest && .venv/bin/python -m pytest worker/tests`.

## Admin dashboard

`https://<PUBLIC_URL>/admin.html`: log in with Discord. You see the servers where you have **Manage Server** or the
`/handcam config admin_role`.

- Grid of every hand cam with a thumbnail refreshed each second, status badge and alert count.
- Click a player: live video, timeline of alerts with snapshots and clips, recordings, **Confirm / False positive /
  Ignore 10m** (the Discord alert is updated too) and **End session**.
- Updates arrive live (Socket.IO); `show info / shadow events` reveals reconnects and shadow-mode menu flags.

Setup: in the Developer Portal → OAuth2, add the redirect `https://<PUBLIC_URL>/auth/callback`; set
`DISCORD_CLIENT_SECRET` and `SESSION_SECRET` (`openssl rand -hex 32`). The dashboard stays off until both are set.

Without the bot: `npm run cli -- new --guild <id> --user <id>` prints a cam link, `npm run cli -- watch --session <id>` a 1-hour watch link.
