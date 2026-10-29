// Admin live view of one session. Link comes from `npm run cli -- watch` (Phase 8: dashboard + OAuth).
(async () => {
  'use strict';
  const { Room, RoomEvent, Track } = LivekitClient;
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.hash.slice(1));
  const url = params.get('url');
  const token = params.get('t');

  const setState = (kind, text) => {
    $('state').className = kind;
    $('state').textContent = text;
  };

  if (!url || !token) return setState('offline', 'Missing watch link');

  const room = new Room({ adaptiveStream: false });
  let current = null;

  room
    .on(RoomEvent.TrackSubscribed, (track) => {
      if (track.source !== Track.Source.Camera) return;
      current = track;
      track.attach($('feed'));
      setState('live', 'LIVE');
    })
    .on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach();
      if (track === current) setState('offline', 'Player camera off');
    })
    .on(RoomEvent.ParticipantDisconnected, (p) => {
      if (p.identity === 'player') setState('offline', 'Player disconnected');
    })
    .on(RoomEvent.Reconnecting, () => setState('offline', 'Reconnecting…'))
    .on(RoomEvent.Reconnected, () => setState(current ? 'live' : '', current ? 'LIVE' : 'Waiting for player'))
    .on(RoomEvent.Disconnected, () => setState('offline', 'Disconnected (link may have expired)'));

  try {
    await room.connect(url, token);
    $('room').textContent = room.name;
    if (!current) setState('', 'Waiting for player');
  } catch {
    return setState('offline', 'Could not connect (link may have expired)');
  }

  setInterval(() => {
    const v = $('feed');
    if (current && v.videoWidth) $('stats').textContent = `${v.videoWidth}×${v.videoHeight}`;
  }, 2_000);
})();
