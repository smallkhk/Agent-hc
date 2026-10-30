import { z } from 'zod';

const schema = z.object({
  PORT: z.coerce.number().int().default(3000),
  PUBLIC_URL: z.url(),
  LIVEKIT_URL: z.string().regex(/^wss?:\/\//),
  LIVEKIT_API_KEY: z.string().min(1),
  LIVEKIT_API_SECRET: z.string().min(1),
  MYSQL_URL: z.string().min(1),
  REDIS_URL: z.string().optional(),
  // Shared secret for the vision worker's /internal calls. Generate: openssl rand -hex 32
  WORKER_SECRET: z.string().min(32),
  STORAGE_DIR: z.string().min(1).default('/var/handcam/recordings'),
  RETENTION_DAYS: z.coerce.number().int().positive().default(7),
  // Optional S3 offload of finished recording chunks. Credentials: standard AWS env / instance role.
  S3_BUCKET: z.string().optional(),
  S3_REGION: z.string().default('us-east-1'),
  S3_ENDPOINT: z.string().optional(), // S3-compatible storage (MinIO, R2, ...)
  S3_PREFIX: z.string().default(''),
  // Admin dashboard (Discord OAuth). Dashboard is off until all three are set.
  DISCORD_CLIENT_ID: z.string().optional(),
  DISCORD_CLIENT_SECRET: z.string().optional(),
  DISCORD_TOKEN: z.string().optional(), // bot token: checks the admin role on login
  SESSION_SECRET: z.string().min(32).optional(),
  DISCORD_API_URL: z.url().default('https://discord.com/api/v10'),
  // Branding shown on the cam page and dashboard.
  BRAND_NAME: z.string().max(40).default('HANDCAM'),
  BRAND_TAGLINE: z.string().max(80).default('Match integrity check'),
  BRAND_ACCENT: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#B14DFF'),
  BRAND_LOGO_URL: z.string().optional(), // e.g. /brand/logo.png (put the file in web/brand/)
  BRAND_BG_URL: z.string().optional(), // background art for hero areas, e.g. /brand/bg.jpg
  DEFAULT_CAM_RES: z.enum(['360p', '480p', '720p']).default('480p'),
  CAM_LINK_TTL_MIN: z.coerce.number().int().positive().default(30),
});

const parsed = schema.safeParse(process.env);
if (!parsed.success) {
  // Only report which keys are wrong, never their values.
  const keys = [...new Set(parsed.error.issues.map((i) => i.path.join('.')))];
  throw new Error(`Invalid or missing env: ${keys.join(', ')}`);
}

export const config = {
  ...parsed.data,
  PUBLIC_URL: parsed.data.PUBLIC_URL.replace(/\/$/, ''),
  secureCookies: parsed.data.PUBLIC_URL.startsWith('https://'),
};
