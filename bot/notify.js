// Posts session lifecycle messages from the Redis bus into each guild's alert channel.
import { SESSIONS_CHANNEL, subscribe } from '../api/lib/bus.js';
import { getGuildConfig } from '../api/lib/guildConfig.js';

const TEXT = {
  live: (m) => `📹 <@${m.discordUserId}> opened their hand cam${m.matchLabel ? ` (${m.matchLabel})` : ''}.`,
  ended: (m) => `⏹️ <@${m.discordUserId}>’s hand cam session ended.`,
  stale: (m) => `⚠️ Lost the feed from <@${m.discordUserId}>’s hand cam.`,
};

export async function startNotifier(client) {
  const sub = await subscribe(SESSIONS_CHANNEL, async (msg) => {
    const text = TEXT[msg.type];
    if (!text) return;
    try {
      const { alertChannelId } = await getGuildConfig(msg.discordGuildId);
      if (!alertChannelId) return;
      const channel = await client.channels.fetch(alertChannelId);
      await channel?.send({ content: text(msg), allowedMentions: { parse: [] } });
    } catch (err) {
      console.error(`notify ${msg.type} for session ${msg.sessionId} failed:`, err.message);
    }
  });
  if (!sub) console.warn('REDIS_URL not set: session notices are off');
  return sub;
}
