import { AccessToken, RoomServiceClient, TrackSource } from 'livekit-server-sdk';
import { randomBytes } from 'node:crypto';
import { config } from '../config.js';

export const roomName = (sessionId) => `handcam-${sessionId}`;

// Player: may only publish its camera. Short TTL; the cam page re-redeems on reconnect.
// canSubscribe stays on so the page receives the worker's "screen detected" data
// messages; the page never subscribes to tracks (autoSubscribe off).
export function playerToken(sessionId) {
  const at = new AccessToken(config.LIVEKIT_API_KEY, config.LIVEKIT_API_SECRET, {
    identity: 'player',
    ttl: '15m',
  });
  at.addGrant({
    roomJoin: true,
    room: roomName(sessionId),
    canPublish: true,
    canPublishSources: [TrackSource.CAMERA],
    canPublishData: false,
    canSubscribe: true,
  });
  return at.toJwt();
}

// Admin viewer: subscribe only, hidden from the player.
export function watchToken(sessionId, viewer = 'admin') {
  const at = new AccessToken(config.LIVEKIT_API_KEY, config.LIVEKIT_API_SECRET, {
    identity: `${viewer}-${randomBytes(4).toString('hex')}`,
    ttl: '1h',
  });
  at.addGrant({
    roomJoin: true,
    room: roomName(sessionId),
    canPublish: false,
    canPublishData: false,
    canSubscribe: true,
    hidden: true,
  });
  return at.toJwt();
}

const rooms = new RoomServiceClient(
  config.LIVEKIT_URL.replace(/^ws/, 'http'),
  config.LIVEKIT_API_KEY,
  config.LIVEKIT_API_SECRET,
);

// Disconnects everyone in the session's room. A missing room is fine (cam never connected).
export async function closeRoom(sessionId) {
  try {
    await rooms.deleteRoom(roomName(sessionId));
  } catch (err) {
    if (err?.status !== 404) console.error(`closeRoom ${sessionId} failed:`, err.message);
  }
}
