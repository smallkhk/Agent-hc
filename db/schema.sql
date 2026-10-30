-- CODM Hand Cam Agent schema (MySQL 8)
-- Apply with: npm run db:migrate (runs this file, then db/migrations/*.sql in order)

CREATE TABLE IF NOT EXISTS guilds (
  id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  discord_guild_id VARCHAR(20)  NOT NULL,
  alert_channel_id VARCHAR(20)  NULL,
  config_json      JSON         NULL,
  created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_guilds_discord (discord_guild_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sessions (
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  guild_id          BIGINT UNSIGNED NOT NULL,
  discord_user_id   VARCHAR(20)  NOT NULL,
  player_name       VARCHAR(100) NULL,               -- Discord display name when the session started
  match_label       VARCHAR(100) NULL,
  status            ENUM('pending','live','stale','ended') NOT NULL DEFAULT 'pending',
  token_hash        CHAR(64)     NOT NULL,           -- sha256 of the one-time cam link token
  token_expires_at  DATETIME(3)  NOT NULL,           -- cam links expire
  token_used_at     DATETIME(3)  NULL,               -- cam links are single-use
  device_hash       CHAR(64)     NULL,               -- sha256 of the cookie that binds the link to the first device
  last_heartbeat_at DATETIME(3)  NULL,               -- worker heartbeat; API marks STALE when missing
  started_at        DATETIME(3)  NULL,
  ended_at          DATETIME(3)  NULL,
  uptime_sec        INT UNSIGNED NOT NULL DEFAULT 0,
  data_bytes        BIGINT UNSIGNED NOT NULL DEFAULT 0,
  UNIQUE KEY uq_sessions_token (token_hash),
  KEY ix_sessions_guild_user (guild_id, discord_user_id),
  KEY ix_sessions_status (status),
  CONSTRAINT fk_sessions_guild FOREIGN KEY (guild_id) REFERENCES guilds(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS events (
  id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id   BIGINT UNSIGNED NOT NULL,
  type         VARCHAR(32)  NOT NULL,                -- SCREEN_CUT_OFF, FEED_FROZEN, mod_menu, ...
  severity     ENUM('info','warning','violation') NOT NULL,
  score        FLOAT        NULL,
  ts           DATETIME(3)  NOT NULL,
  frame_path   VARCHAR(512) NULL,
  clip_path    VARCHAR(512) NULL,
  llm_verdict  TEXT         NULL,
  admin_action ENUM('confirmed','false_positive','ignored') NULL,
  admin_id     VARCHAR(20)  NULL,
  resolved_at  DATETIME(3)  NULL,
  KEY ix_events_session_ts (session_id, ts),
  KEY ix_events_retention (ts, admin_action),
  KEY ix_events_unresolved (admin_action, severity),
  CONSTRAINT fk_events_session FOREIGN KEY (session_id) REFERENCES sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recordings (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id  BIGINT UNSIGNED NOT NULL,
  path        VARCHAR(512) NOT NULL,
  started_at  DATETIME(3)  NOT NULL,
  ended_at    DATETIME(3)  NULL,
  size_bytes  BIGINT UNSIGNED NOT NULL DEFAULT 0,
  keep        BOOLEAN      NOT NULL DEFAULT FALSE,   -- true while a flagged event is unresolved
  UNIQUE KEY uq_recordings_path (path),
  KEY ix_recordings_session (session_id),
  KEY ix_recordings_retention (keep, started_at),
  CONSTRAINT fk_recordings_session FOREIGN KEY (session_id) REFERENCES sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS training_samples (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  event_id    BIGINT UNSIGNED NULL,
  image_path  VARCHAR(512) NOT NULL,
  label       VARCHAR(32)  NOT NULL,
  source      ENUM('admin','manual') NOT NULL,
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY ix_training_label (label),
  CONSTRAINT fk_training_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
