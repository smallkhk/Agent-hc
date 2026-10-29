# CODM Hand Cam Agent

AI-assisted hand cam monitoring for Call of Duty: Mobile lobbies, run through Discord.
Players stream a second camera pointed at their phone or iPad. The agent watches the whole session and flags:

1. Screen not fully inside the camera frame (or screen off or unreadable)
2. Hack or mod menus and overlays visible on the game screen
3. Stream tampering (frozen feed, looped or pre-recorded video, drops)

**Out of scope:** touch or hand verification, controllers, invisible hacks with no on-screen trace. The AI flags; **admins decide**. No auto-bans.

---

## Stack

| Layer | Tech |
|---|---|
| Discord bot + API + web | Node.js 20, discord.js v14, Express, Socket.IO |
| Video | LiveKit (self-hosted, Docker), WebRTC |
| Vision worker | Python 3.11, livekit-rtc SDK, OpenCV, ONNX Runtime, imagehash |
| Hack-menu model | MobileNetV3 / EfficientNet-B0 classifier → ONNX (Apache/MIT, **no Ultralytics/AGPL**) |
| Optional 2nd opinion | Vision LLM API on flagged frames only (feature flag, off by default) |
| DB | MySQL 8 |
| Storage | Local disk → optional S3 (lifecycle: delete clean recordings after 7 days) |
| Hosting | Ubuntu (EC2 or VPS), PM2, Nginx reverse proxy, Let's Encrypt |

---

## Architecture

```
Player cam device (browser) ──WebRTC──► LiveKit server
                                            │
                       Python vision worker subscribes per session
                       ├─ samples 1–2 fps
                       ├─ screen detection (OpenCV)
                       ├─ menu classifier (ONNX)
                       ├─ freeze/loop detection
                       ├─ chunked recording (FFmpeg, 10-min files)
                       └─ events ──► Node API (HTTP/Redis pub-sub)
                                            │
                       Node API ──► MySQL, Discord bot, admin dashboard
```

---

## Directory layout

```
/bot          discord.js bot (slash commands, embeds, admin buttons)
/api          Express API, LiveKit token minting, events intake, Socket.IO
/web          static pages: player cam page, admin live dashboard
/worker       Python vision worker
  /detect     screen.py, menu.py, integrity.py
  /models     menu_classifier.onnx (+ labels.json)
  /record     chunked recorder
/training     dataset tools + classifier training script (PyTorch → ONNX)
/deploy       docker-compose (livekit, redis), nginx conf, pm2 ecosystem.config.js
/db           schema.sql, migrations
.env.example
```

---

## Discord commands

| Command | Who | Action |
|---|---|---|
| `/handcam start @player [match]` | Admin | Create session, DM player a one-time cam link |
| `/handcam join` | Player | Self-start if lobby requires it |
| `/handcam status [@player]` | Anyone | ✅ OK / ⚠️ Warning / ❌ Violation + uptime |
| `/handcam stop @player` | Admin | End session, finalize recordings |
| `/handcam lobby start/stop` | Admin | Start or stop sessions for all players in a lobby role/channel |
| `/handcam config` | Admin | Set thresholds and the alert channel per server |

**Alert embed** in the admin channel: player, rule, timestamp, thumbnail, 20s clip link, plus buttons **[Confirm] [False positive] [Ignore 10m]**.
Admin button choices are saved as training labels.

---

## Player cam page (`/web/cam.html`)

- Opened from the DM link on a **second device** (phone, tablet, laptop webcam).
- Token in URL → API mints LiveKit token (expires; single session).
- Rear camera by default, camera switcher, torch toggle if available.
- **Low-data defaults:** 480p @ 15fps, ~400–600 kbps. Options: 360p (Data saver) / 720p.
- Setup overlay: live preview with a guide box ("Fit your whole screen inside the box"), green when the server confirms screen detected.
- Keep-awake (Wake Lock API), auto-reconnect, visible "LIVE / Reconnecting" state.
- Shows data used so far.

---

## Detection rules

### 1. Screen in frame (`detect/screen.py`)
- Find the largest bright quadrilateral (Canny + contours + `approxPolyDP`, fallback adaptive threshold).
- **Pass** if: 4 corners found, all corners ≥ `EDGE_MARGIN_PX` (default 8) from frame border, screen area ≥ `MIN_SCREEN_AREA` (default 15% of frame), aspect ratio fits phone/iPad landscape (≈1.3–2.3), mean brightness above `MIN_BRIGHTNESS`.
- Warnings: `SCREEN_CUT_OFF`, `SCREEN_TOO_SMALL`, `SCREEN_NOT_FOUND`, `SCREEN_DARK`, `GLARE` (high % saturated pixels in screen region).
- Grace period: warning after `GRACE_SEC` (default 10s) continuous failure, violation after `VIOLATION_SEC` (default 30s).
- Track corners over time; smooth with EMA to avoid flicker.

### 2. Hack menu / overlay (`detect/menu.py`)
- Perspective-warp the detected screen to a flat image (e.g. 448×224).
- Run ONNX classifier → classes: `normal_gameplay`, `codm_menu_ui` (lobby, settings, loadout = allowed), `mod_menu`, `esp_overlay`, `unknown_overlay`.
- Flag if suspicious-class probability ≥ `MENU_THRESHOLD` (default 0.8) on **2 of the last 3** samples.
- On flag: save frame and a 20s clip (10s before / 10s after, from ring buffer).
- Optional (`LLM_SECOND_OPINION=true`): send flattened frame to vision LLM with a fixed prompt; attach its verdict to the alert. Rate-limit per session.
- Sample rate: 2 fps while gameplay is detected (menus can be flashed quickly).

### 3. Stream integrity (`detect/integrity.py`)
- **Freeze:** mean abs frame diff < `FREEZE_DIFF` for > `FREEZE_SEC` (default 8s) while screen is on → `FEED_FROZEN`.
- **Loop / replay:** keep pHash ring buffer (~10 min); a run of ≥ `LOOP_MATCH_RUN` consecutive frames (default 20) matching an earlier sequence → `FEED_LOOPED`.
- **Drops:** disconnect > `DROP_SEC` (default 20s) → `STREAM_DROPPED`; log every reconnect.
- **Camera change:** sudden full-scene change (background hash shift) → `SCENE_CHANGED` warning (possible device swap).

---

## Long sessions (hours)

- Worker handles many sessions concurrently (asyncio, one task per session, shared ONNX session).
- Bounded memory: ring buffers only, no full-session frames in RAM.
- Recording: FFmpeg segment muxer, 10-min MP4 chunks per session at stream resolution.
- Retention: clean chunks deleted after `RETENTION_DAYS` (7); chunks with flags kept until the admin resolves them.
- Heartbeats: worker → API every 10s per session; API marks session `STALE` if missing.
- Worker auto-restart via PM2; sessions resume on restart from DB state.
- Per-session stats: uptime %, warnings, violations, data used.

---

## Database (MySQL)

```
guilds(id, discord_guild_id, alert_channel_id, config_json, created_at)
sessions(id, guild_id, discord_user_id, match_label, status[pending|live|stale|ended],
         token_hash, started_at, ended_at, uptime_sec, data_bytes)
events(id, session_id, type, severity[info|warning|violation], score, ts,
       frame_path, clip_path, llm_verdict, admin_action[confirmed|false_positive|ignored|null],
       admin_id, resolved_at)
recordings(id, session_id, path, started_at, ended_at, size_bytes, keep[bool])
training_samples(id, event_id, image_path, label, source[admin|manual], created_at)
```

---

## Admin dashboard (`/web/admin.html`)

- Discord OAuth login, role-gated.
- Grid of live player feeds (low-res thumbnails, refresh 1/s) with status badges.
- Click → full live view + event timeline + clips.
- Resolve events (same as Discord buttons).

---

## Classifier training (`/training`)

1. `collect.py`: extract flattened screen crops from recordings / screenshots into `dataset/<class>/`.
2. Sources: normal CODM gameplay (many maps/modes, phone + iPad, different brightness), CODM's own menus, mod-menu & ESP screenshots/videos, admin-labeled events.
3. `train.py`: PyTorch, pretrained MobileNetV3/EfficientNet-B0, augmentation (perspective, blur, glare, compression, color jitter), class-balanced.
4. Export to ONNX; save `labels.json` and metrics (precision/recall per class).
5. Retrain periodically from `training_samples` (admin-confirmed + false positives).
6. Until the model is good: run in **shadow mode** (log only, no alerts for menu rule).

---

## Config (`.env.example`)

```
DISCORD_TOKEN=
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
PUBLIC_URL=https://handcam.example.com
LIVEKIT_URL=wss://lk.example.com
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
MYSQL_URL=mysql://user:pass@localhost:3306/handcam
REDIS_URL=redis://localhost:6379
STORAGE_DIR=/var/handcam/recordings
S3_BUCKET=
RETENTION_DAYS=7
SAMPLE_FPS=2
GRACE_SEC=10
VIOLATION_SEC=30
MENU_THRESHOLD=0.8
FREEZE_SEC=8
DROP_SEC=20
LLM_SECOND_OPINION=false
LLM_API_KEY=
DEFAULT_CAM_RES=480p
```

---

## Build phases

1. **Infra:** docker-compose (LiveKit + Redis), Nginx + TLS for app and LiveKit, MySQL schema, PM2 config.
2. **Streaming:** cam page → LiveKit; admin can watch the live feed; token flow from Discord DM.
3. **Bot:** slash commands, sessions in DB, status embeds.
4. **Worker v1:** subscribe to streams, screen-in-frame rule, freeze/drop rules, alerts to Discord.
5. **Recording:** chunked recording, clip extraction, retention job.
6. **Loop detection.**
7. **Menu classifier:** dataset tools, training, ONNX inference in shadow mode → enable alerts.
8. **Admin dashboard.**
9. **Optional:** LLM second opinion, S3 offload, multi-lobby scaling.

## Acceptance tests

- Screen partly out of frame for 30s → violation alert with clip.
- Screen fully in frame for a 3-hour test session → zero false screen alerts.
- Looping a pre-recorded clip into the cam → `FEED_LOOPED` within 60s.
- Covering the camera / freezing → `FEED_FROZEN` within 10s.
- Mod menu screenshot shown on device screen → `mod_menu` flag (once the model is trained).
- 20 concurrent 480p sessions on one 8-vCPU server, with CPU under 75% sustained.
- Worker restart mid-session → sessions resume, no lost recordings older than the current chunk.

## Conventions

- Node: ES modules, async/await, zod for input validation.
- Python: type hints, asyncio, config from env only.
- Never log tokens or secrets. Cam links are single-use and expire.
- All thresholds configurable per guild via `/handcam config`.
