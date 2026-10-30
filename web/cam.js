// Player cam page: publishes the second-device camera to LiveKit.
(() => {
  'use strict';
  const { Room, RoomEvent, Track, VideoPreset, createLocalVideoTrack } = LivekitClient;

  // Low-data defaults: 15 fps, bitrate per quality level.
  const PRESETS = {
    '360p': new VideoPreset(640, 360, 300_000, 15),
    '480p': new VideoPreset(854, 480, 500_000, 15),
    '720p': new VideoPreset(1280, 720, 1_200_000, 15),
  };
  const SCREEN_TOPIC = 'handcam.screen'; // sent by the vision worker: {"ok":bool,"reason":string}
  const STATS_EVERY_MS = 5_000;
  const REPORT_EVERY_MS = 30_000;

  const $ = (id) => document.getElementById(id);
  const linkToken = new URLSearchParams(location.hash.slice(1)).get('t');

  let room = null;
  let track = null;
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  let res = store.get('hc_res') || '480p';
  let facing = 'environment';
  let torchOn = false;
  let wakeLock = null;
  let stopped = false;
  let retryDelay = 2_000;
  let lastSenderBytes = 0;
  let totalBytes = 0;
  let unreportedBytes = 0;
  let liveSince = null;

  const radios = () => [...document.querySelectorAll('input[name="res"]')];
  const pickRes = (value) => radios().forEach((r) => { r.checked = r.value === value; });
  pickRes(res);
  $('preview').addEventListener('resize', (e) => {
    const { videoWidth: w, videoHeight: h } = e.target;
    if (w && h) $('frame').style.setProperty('--ar', `${w} / ${h}`);
  });

  const BLOCKED = {
    invalid: ['Link not valid', 'This cam link does not work. Use the latest link the bot sent you.'],
    expired: ['Link expired', 'This link timed out before it was opened. Run /handcam join in Discord or ask an admin for a new one.'],
    used: ['Already in use', 'This link is already live on another device. Each link works on one device only.'],
    ended: ['Session ended', 'This hand cam session is over. Thanks for playing fair. You can close this page.'],
  };

  // Full-screen "can't continue" state. `message` is what the player needs to do next.
  function showError(message, { title = "Can't start", kind = 'error', retry = false } = {}) {
    stopped = kind === 'ended' || stopped;
    $('start').hidden = true;
    $('live').hidden = true;
    $('blocked').hidden = false;
    $('blocked').querySelector('.blocked').classList.toggle('ended', kind === 'ended');
    $('blocked-icon').querySelector('use').setAttribute('href', kind === 'ended' ? '#i-flag' : '#i-alert');
    $('error-title').textContent = title;
    $('error').textContent = message;
    $('retry').hidden = !retry;
    $('go').disabled = false;
  }

  function showCode(code, fallback) {
    const [title, message] = BLOCKED[code] ?? ["Can't start", fallback];
    showError(message, { title, kind: code });
  }

  function setState(kind, text) {
    $('live-pill').className = `live-pill ${kind}`;
    $('state').textContent = text;
    $('reconnect').hidden = kind === 'live' || kind === '';
    if (kind === 'live' && !liveSince) liveSince = Date.now();
  }

  setInterval(() => {
    if (!liveSince) return;
    const s = Math.floor((Date.now() - liveSince) / 1000);
    const h = Math.floor(s / 3600);
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    $('elapsed').textContent = h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  }, 1000);

  async function redeem() {
    const r = await fetch('/api/cam/redeem', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ token: linkToken }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(body.error || 'Could not start the hand cam.');
      err.fatal = r.status >= 400 && r.status < 500;
      err.code = body.code;
      throw err;
    }
    return body;
  }

  async function makeTrack() {
    return createLocalVideoTrack({ facingMode: facing, resolution: PRESETS[res].resolution });
  }

  async function publish() {
    await room.localParticipant.publishTrack(track, {
      source: Track.Source.Camera,
      simulcast: false,
      videoEncoding: PRESETS[res].encoding,
      degradationPreference: 'maintain-resolution', // readable screen beats smooth motion
    });
    lastSenderBytes = 0;
  }

  async function connect() {
    const { livekitUrl, livekitToken } = await redeem();
    room = new Room({ adaptiveStream: false, dynacast: false, disconnectOnPageLeave: false });
    room
      .on(RoomEvent.Reconnecting, () => setState('reconnecting', 'Reconnecting…'))
      .on(RoomEvent.Reconnected, () => setState('live', 'LIVE'))
      .on(RoomEvent.Disconnected, onDisconnected)
      .on(RoomEvent.DataReceived, onData);
    await room.connect(livekitUrl, livekitToken, { autoSubscribe: false });
    await publish();
    retryDelay = 2_000;
    setState('live', 'LIVE');
  }

  function onDisconnected() {
    if (stopped) return;
    setState('offline', 'Reconnecting…');
    setGuide(null);
    setTimeout(async () => {
      try {
        await connect();
      } catch (err) {
        if (err.fatal) return showCode(err.code, err.message);
        retryDelay = Math.min(retryDelay * 2, 30_000);
        onDisconnected();
      }
    }, retryDelay);
  }

  function setGuide(status) {
    const guide = $('guide');
    guide.classList.toggle('ok', status?.ok === true);
    guide.classList.toggle('bad', status?.ok === false);
    $('guide-text').textContent = status?.ok
      ? 'Screen locked'
      : status?.reason || 'Fit your whole screen inside the brackets';
  }

  function onData(payload, _participant, _kind, topic) {
    if (topic !== SCREEN_TOPIC) return;
    try {
      setGuide(JSON.parse(new TextDecoder().decode(payload)));
    } catch {
      // ignore malformed messages
    }
  }

  async function updateDataUsed() {
    if (!track) return;
    const stats = await track.getSenderStats().catch(() => []);
    const sent = stats.reduce((sum, s) => sum + (s.bytesSent || 0), 0);
    // A new peer connection or republish restarts the sender counter.
    const delta = sent >= lastSenderBytes ? sent - lastSenderBytes : sent;
    lastSenderBytes = sent;
    totalBytes += delta;
    unreportedBytes += delta;
    $('data').textContent = `${(totalBytes / 1e6).toFixed(1)} MB`;
  }

  async function reportDataUsed() {
    if (!unreportedBytes) return;
    const bytesSent = unreportedBytes;
    unreportedBytes = 0;
    const r = await fetch('/api/cam/stats', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'same-origin',
      keepalive: true, // still sent when the page is closing
      body: JSON.stringify({ token: linkToken, bytesSent }),
    }).catch(() => null);
    if (!r?.ok) unreportedBytes += bytesSent;
  }

  async function keepAwake() {
    if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
    } catch {
      // denied (e.g. low battery); the hint tells the player to keep the page open
    }
  }

  function setupTorch() {
    const caps = track.mediaStreamTrack.getCapabilities?.() || {};
    $('torch').hidden = !caps.torch;
    torchOn = false;
    $('torch').setAttribute('aria-pressed', 'false');
  }

  async function replaceTrack() {
    const old = track;
    if (room && old) await room.localParticipant.unpublishTrack(old);
    old?.stop();
    track = await makeTrack();
    track.attach($('preview'));
    setupTorch();
    if (room?.state === 'connected') await publish();
  }

  $('go').addEventListener('click', async () => {
    $('go').disabled = true;
    res = radios().find((r) => r.checked)?.value || '480p';
    store.set('hc_res', res);
    try {
      track = await makeTrack();
    } catch {
      return showError('Allow camera access for this page in your browser settings, then try again.', {
        title: 'Camera blocked',
        retry: true,
      });
    }
    $('start').hidden = true;
    $('live').hidden = false;
    $('res-live').value = res;
    track.attach($('preview'));
    setupTorch();
    keepAwake();
    setInterval(updateDataUsed, STATS_EVERY_MS);
    setInterval(reportDataUsed, REPORT_EVERY_MS);
    try {
      await connect();
    } catch (err) {
      if (err.fatal) return showCode(err.code, err.message);
      onDisconnected();
    }
  });

  $('retry').addEventListener('click', () => {
    $('blocked').hidden = true;
    $('start').hidden = false;
  });

  $('flip').addEventListener('click', async () => {
    facing = facing === 'environment' ? 'user' : 'environment';
    await track.restartTrack({ facingMode: facing, resolution: PRESETS[res].resolution });
    setupTorch();
  });

  $('torch').addEventListener('click', async () => {
    torchOn = !torchOn;
    $('torch').setAttribute('aria-pressed', String(torchOn));
    await track.mediaStreamTrack.applyConstraints({ advanced: [{ torch: torchOn }] }).catch(() => {});
  });

  $('res-live').addEventListener('change', async (e) => {
    res = e.target.value;
    store.set('hc_res', res);
    await replaceTrack();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') keepAwake();
  });
  window.addEventListener('pagehide', () => {
    stopped = true;
    reportDataUsed();
  });

  // Start screen: greet the player and catch dead links before asking for the camera.
  async function peek() {
    const r = await fetch('/api/cam/peek', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ token: linkToken }),
    }).catch(() => null);
    const info = await r?.json().catch(() => null);
    if (!info) return;
    if (BLOCKED[info.state]) return showCode(info.state);
    if (info.playerName) {
      const h = $('hello');
      h.textContent = 'Ready, ';
      const name = document.createElement('em');
      name.textContent = info.playerName;
      h.append(name);
    }
    if (info.matchLabel) {
      $('match').textContent = info.matchLabel;
      $('match').hidden = false;
      $('hud-match').textContent = info.matchLabel;
    }
    if (info.state === 'resume') $('go').lastChild.textContent = ' Resume';
  }

  if (!linkToken) {
    showError('Open the hand cam link the bot sent you in Discord.', { title: 'No cam link' });
  } else if (!navigator.mediaDevices?.getUserMedia) {
    showError('This browser cannot use the camera. Open the link in Chrome or Safari.', { title: 'No camera access' });
  } else {
    peek();
  }
})();
