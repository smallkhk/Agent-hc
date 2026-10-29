import { z } from 'zod';

const schema = z.object({
  DISCORD_TOKEN: z.string().min(1),
  DISCORD_CLIENT_ID: z.string().regex(/^\d{17,20}$/),
  // Register commands to one server instantly while testing; global otherwise (can take a while to show up).
  DISCORD_DEV_GUILD_ID: z.string().regex(/^\d{17,20}$/).optional().or(z.literal('')),
  // Privileged intent, needed only for role-based lobbies. Enable it in the Developer Portal first.
  DISCORD_MEMBERS_INTENT: z.enum(['true', 'false', '']).optional(),
});

const parsed = schema.safeParse(process.env);
if (!parsed.success) {
  const keys = [...new Set(parsed.error.issues.map((i) => i.path.join('.')))];
  throw new Error(`Invalid or missing env: ${keys.join(', ')}`);
}

export const botConfig = {
  ...parsed.data,
  membersIntent: parsed.data.DISCORD_MEMBERS_INTENT === 'true',
};
