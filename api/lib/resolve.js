// Admin decision on an alert, from a Discord button or the dashboard.
import { mute, publish } from './bus.js';
import { getEvent, resolveEvent } from './events.js';

export const RESOLVED_CHANNEL = 'handcam:resolved';
export const IGNORE_SEC = 600;
export const ACTIONS = { confirm: 'confirmed', fp: 'false_positive', ignore: 'ignored' };

// Returns { ok, event } — ok false when someone else resolved it first.
export async function resolveAlert(eventId, key, adminId, { source }) {
  const action = ACTIONS[key];
  if (!action) throw new Error(`unknown action ${key}`);
  const ok = await resolveEvent(eventId, action, adminId);
  const event = await getEvent(eventId);
  if (ok && action === 'ignored') await mute(event.sessionId, event.type, IGNORE_SEC);
  // The Discord button path updates its own message; the dashboard asks the bot to.
  if (ok && source === 'dashboard') await publish({ eventId, action, adminId }, RESOLVED_CHANNEL);
  return { ok, event };
}
