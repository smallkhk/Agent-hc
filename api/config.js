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
