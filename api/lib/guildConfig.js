// Per-guild settings. Thresholds default to the env values; /handcam config overrides them.
import { z } from 'zod';
import { pool } from '../db.js';
import { ensureGuild } from './sessions.js';
import { THRESHOLDS } from './thresholds.js';

export { THRESHOLDS };

const threshold = ({ min, max, int }) => (int ? z.number().int() : z.number()).min(min).max(max);

// Only overrides are stored, so changing an env default still reaches guilds that never set it.
export const configPatchSchema = z
  .object({
    ...Object.fromEntries(Object.entries(THRESHOLDS).map(([k, t]) => [k, threshold(t)])),
    selfJoin: z.boolean(),
    adminRoleId: z.string().regex(/^\d{17,20}$/).nullable(),
  })
  .partial();

const DEFAULTS = {
  ...Object.fromEntries(Object.entries(THRESHOLDS).map(([k, t]) => [k, t.default])),
  selfJoin: true,
  adminRoleId: null,
};

async function loadGuild(discordGuildId) {
  const [rows] = await pool.query(
    'SELECT alert_channel_id, config_json FROM guilds WHERE discord_guild_id = ?',
    [discordGuildId],
  );
  const row = rows[0];
  const raw = typeof row?.config_json === 'string' ? JSON.parse(row.config_json) : row?.config_json;
  // Drop stored values that no longer validate (e.g. bounds tightened later).
  const overrides = configPatchSchema.safeParse(raw ?? {});
  return { alertChannelId: row?.alert_channel_id ?? null, overrides: overrides.success ? overrides.data : {} };
}

export async function getGuildConfig(discordGuildId) {
  const { alertChannelId, overrides } = await loadGuild(discordGuildId);
  return { ...DEFAULTS, ...overrides, alertChannelId };
}

export class ConfigError extends Error {}

// patch: subset of configPatchSchema plus alertChannelId (stored in its own column).
export async function updateGuildConfig(discordGuildId, { alertChannelId, ...patch }) {
  await ensureGuild(discordGuildId);
  const { overrides } = await loadGuild(discordGuildId);
  const given = Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined));
  const parsed = configPatchSchema.safeParse({ ...overrides, ...given });
  if (!parsed.success) throw new ConfigError(parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; '));
  const merged = { ...DEFAULTS, ...parsed.data };
  if (merged.violationSec <= merged.graceSec) {
    throw new ConfigError(`violationSec (${merged.violationSec}) must be longer than graceSec (${merged.graceSec})`);
  }
  await pool.query(
    `UPDATE guilds SET config_json = ?, alert_channel_id = COALESCE(?, alert_channel_id)
     WHERE discord_guild_id = ?`,
    [JSON.stringify(parsed.data), alertChannelId ?? null, discordGuildId],
  );
  return getGuildConfig(discordGuildId);
}
