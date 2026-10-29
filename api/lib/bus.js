// Redis pub-sub between the API, the vision worker and the bot.
// Channel handcam:sessions carries {type: live|ended|stale, sessionId, discordGuildId, discordUserId, matchLabel}.
import { createClient } from 'redis';
import { config } from '../config.js';

export const SESSIONS_CHANNEL = 'handcam:sessions';
// {eventId} for each warning/violation that should alert admins.
export const EVENTS_CHANNEL = 'handcam:events';

let client = null;

function connect() {
  client ??= createClient({ url: config.REDIS_URL })
    .on('error', (err) => console.error('redis:', err.message))
    .connect();
  return client;
}

// Best effort: a Redis outage must not fail the request that triggered the message.
export async function publish(message, channel = SESSIONS_CHANNEL) {
  if (!config.REDIS_URL) return;
  try {
    await (await connect()).publish(channel, JSON.stringify(message));
  } catch (err) {
    console.error(`publish to ${channel} failed:`, err.message);
  }
}

export async function subscribe(channel, onMessage) {
  if (!config.REDIS_URL) return null;
  const sub = createClient({ url: config.REDIS_URL }).on('error', (err) => console.error('redis:', err.message));
  await sub.connect();
  await sub.subscribe(channel, (raw) => {
    try {
      onMessage(JSON.parse(raw));
    } catch (err) {
      console.error(`bad message on ${channel}:`, err.message);
    }
  });
  return sub;
}

// "Ignore 10m": alerts of one type for one session are stored but not posted.
const muteKey = (sessionId, type) => `handcam:mute:${sessionId}:${type}`;

export async function mute(sessionId, type, seconds) {
  if (!config.REDIS_URL) return;
  await (await connect()).set(muteKey(sessionId, type), '1', { EX: seconds });
}

export async function isMuted(sessionId, type) {
  if (!config.REDIS_URL) return false;
  try {
    return Boolean(await (await connect()).exists(muteKey(sessionId, type)));
  } catch {
    return false; // fail open: better a duplicate alert than a missed one
  }
}
