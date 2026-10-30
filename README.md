# CODM Hand Cam Agent

AI-assisted hand cam monitoring for Call of Duty: Mobile lobbies, run through Discord. Full spec: [CLAUDE.md](CLAUDE.md).

Discord bots can't watch voice-channel video, so players open a one-time cam link (sent by the bot) on a second device.
That page streams to the self-hosted LiveKit server, where admins watch and the vision worker analyses the feed.

## Setup

1. **Server:** Ubuntu with Docker, Node 20.12+, Python 3.11, FFmpeg, MySQL 8, Nginx. Open UDP 50000–60000 and TCP 7881 for LiveKit media.
2. `cp .env.example .env` and fill it in (`WORKER_SECRET`: `openssl rand -hex 32`). `npm ci`, then `npm run db:migrate`.
   Vision worker: `python3.11 -m venv .venv && .venv/bin/pip install -r worker/requirements.txt`.
3. `cd deploy && docker compose --env-file ../.env up -d` (LiveKit + Redis).
4. Nginx: copy `deploy/nginx/handcam.conf`, replace the domains, run certbot.
5. **Discord app** ([Developer Portal](https://discord.com/developers/applications)):
   - Bot tab: copy the token into `DISCORD_TOKEN`. Application ID → `DISCORD_CLIENT_ID`.
   - Invite with scopes `bot` + `applications.commands` and permissions View Channels, Send Messages, Embed Links.
   - Role-based lobbies (`/handcam lobby start role:`) need **Server Members Intent** turned on, plus `DISCORD_MEMBERS_INTENT=true`.
     Voice-channel lobbies work without it.
6. `npm run bot:deploy` registers `/handcam` (set `DISCORD_DEV_GUILD_ID` to register to one server instantly while testing).
7. `pm2 start deploy/ecosystem.config.cjs`
8. In Discord: `/handcam config alert_channel:#handcam-alerts`.

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

Worker tests (need `ffmpeg`): `.venv/bin/pip install pytest && .venv/bin/python -m pytest worker/tests`.

Without the bot: `npm run cli -- new --guild <id> --user <id>` prints a cam link, `npm run cli -- watch --session <id>` a 1-hour watch link.
