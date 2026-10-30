// Admin dashboard: live grid of hand cams, session detail with live view, timeline and recordings.
(() => {
  'use strict';
  const { Room, RoomEvent, Track } = LivekitClient;
  const $ = (id) => document.getElementById(id);

  const RULE_TEXT = {
    SCREEN_CUT_OFF: 'Screen partly out of frame',
    SCREEN_TOO_SMALL: 'Screen too small',
    SCREEN_NOT_FOUND: 'Screen not visible',
    SCREEN_DARK: 'Screen off or too dark',
    GLARE: 'Glare hides the screen',
    FEED_FROZEN: 'Camera feed frozen',
    STREAM_DROPPED: 'Hand cam disconnected',
    STREAM_RECONNECTED: 'Hand cam reconnected',
    FEED_LOOPED: 'Feed looped / replayed',
    SCENE_CHANGED: 'Camera scene changed',
    mod_menu: 'Mod menu on screen',
    esp_overlay: 'ESP overlay on screen',
    unknown_overlay: 'Unknown overlay on screen',
    normal_gameplay: 'Normal gameplay',
    codm_menu_ui: 'CODM menu',
  };
  const ACTION_TEXT = { confirmed: '✅ Confirmed', false_positive: '👍 False positive', ignored: '🔕 Ignored' };

  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  let me = null;
  let guild = null;
  let sessions = [];
  let openId = null;
  let room = null;

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  const media = (rel) => `/admin/media/${rel}`;
  const fmtTime = (t) => new Date(t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const fmtDur = (sec) => {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    return h ? `${h}h ${m}m` : `${m}m ${sec % 60}s`;
  };
  const playerName = (s) => s.playerName || `User ${s.discordUserId}`;

  async function api(path, init = {}) {
    const r = await fetch(path, {
      ...init,
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json', 'x-handcam': '1', ...init.headers },
    });
    if (r.status === 401) return showLogin();
    const body = await r.json().catch(() => ({}));
    if (!r.ok && r.status !== 409) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  }

  function showLogin() {
    for (const id of ['top', 'grid-wrap', 'detail']) $(id).hidden = true;
    $('login').hidden = false;
    return null;
  }

  function badge(s) {
    if (s.status === 'ended') return { cls: '', text: 'Ended', card: '' };
    if (s.status === 'pending') return { cls: '', text: 'Waiting for cam', card: '' };
    if (Number(s.openViolations)) return { cls: 'bad', text: `❌ ${s.openViolations} violation${s.openViolations > 1 ? 's' : ''}`, card: 'violation' };
    if (s.status === 'stale') return { cls: 'warn', text: '⚠️ Not being checked', card: 'warning' };
    if (Number(s.openWarnings)) return { cls: 'warn', text: `⚠️ ${s.openWarnings} warning${s.openWarnings > 1 ? 's' : ''}`, card: 'warning' };
    return { cls: 'ok', text: '✅ OK', card: '' };
  }

  // --- grid ---------------------------------------------------------------------------------

  async function loadSessions() {
    if (!guild) return;
    const body = await api(`/admin/api/sessions?guild=${guild}`);
    if (!body) return;
    sessions = body.sessions;
    renderGrid();
  }

  function renderGrid() {
    const live = sessions.filter((s) => s.status === 'live').length;
    const flagged = sessions.filter((s) => s.status !== 'ended' && Number(s.openViolations)).length;
    $('counts').innerHTML = `<span class="pill live">${live} live</span>` +
      (flagged ? `<span class="pill bad">${flagged} with violations</span>` : '');
    $('empty').hidden = sessions.length > 0;
    $('grid').innerHTML = sessions.map((s) => {
      const b = badge(s);
      const since = s.startedAt ? fmtDur((Date.now() - new Date(s.startedAt)) / 1000) : '—';
      const thumb = s.status === 'live' || s.status === 'stale'
        ? `<img data-thumb="${s.id}" alt="" src="/admin/api/sessions/${s.id}/thumb.jpg?t=${Date.now()}">`
        : `<span>${s.status === 'pending' ? 'Link not opened yet' : 'Ended'}</span>`;
      return `<button class="card ${b.card}" data-id="${s.id}">
        <div class="thumb">${thumb}${s.status === 'live' ? '<span class="pill live">LIVE</span>' : ''}</div>
        <div class="card-body">
          <div class="card-title"><span>${esc(playerName(s))}</span><span class="pill ${b.cls}">${b.text}</span></div>
          <div class="muted">${esc(s.matchLabel || 'No match label')} · ${{ ended: 'ended', pending: 'waiting' }[s.status] ?? `live ${since}`} · ${s.alerts} alert${s.alerts == 1 ? '' : 's'}</div>
        </div>
      </button>`;
    }).join('');
  }

  // Thumbnails refresh once a second; a new image only replaces the old one once it has loaded.
  setInterval(() => {
    if (document.hidden) return;
    for (const img of document.querySelectorAll('img[data-thumb]')) {
      const next = new Image();
      next.onload = () => { img.src = next.src; };
      next.src = `/admin/api/sessions/${img.dataset.thumb}/thumb.jpg?t=${Date.now()}`;
    }
  }, 1000);

  // --- detail -------------------------------------------------------------------------------

  async function openDetail(id) {
    openId = id;
    $('detail').hidden = false;
    $('live').hidden = true;
    await loadDetail();
  }

  function closeDetail() {
    openId = null;
    $('detail').hidden = true;
    stopWatching();
  }

  async function loadDetail() {
    if (!openId) return;
    const body = await api(`/admin/api/sessions/${openId}`);
    if (!body) return;
    const { session: s, events, recordings } = body;
    const b = badge({ ...s, openViolations: events.filter((e) => e.severity === 'violation' && !e.adminAction).length,
      openWarnings: events.filter((e) => e.severity === 'warning' && !e.adminAction).length });
    $('d-name').textContent = playerName(s);
    const up = s.startedAt ? fmtDur(((s.endedAt ? new Date(s.endedAt) : Date.now()) - new Date(s.startedAt)) / 1000) : '—';
    $('d-meta').innerHTML = `<span class="pill ${b.cls}">${b.text}</span> ${esc(s.matchLabel || '')} · ${up} · ` +
      `${(Number(s.dataBytes) / 1e6).toFixed(0)} MB · Discord ID ${esc(s.discordUserId)}`;
    const active = s.status !== 'ended';
    $('d-watch').hidden = !active;
    $('d-stop').hidden = !active;

    const showInfo = $('show-info').checked;
    const shown = events.filter((e) => showInfo || e.severity !== 'info');
    $('timeline').innerHTML = shown.length ? shown.map(eventRow).join('') : '<li class="muted">No alerts.</li>';
    $('recordings').innerHTML = recordings.length
      ? recordings.map((r) => `<li><a href="${media(r.path)}" target="_blank" rel="noopener">${fmtTime(r.startedAt)}–${r.endedAt ? fmtTime(r.endedAt) : 'recording'}</a>
          <span class="muted">${(Number(r.sizeBytes) / 1e6).toFixed(1)} MB${r.keep ? ' · kept (unresolved alert)' : ''}</span></li>`).join('')
      : '<li class="muted">No recordings yet.</li>';
  }

  function eventRow(e) {
    const sev = e.severity === 'violation' ? ['bad', 'Violation'] : e.severity === 'warning' ? ['warn', 'Warning'] : ['', 'Info'];
    const shadow = e.severity === 'info' && ['mod_menu', 'esp_overlay', 'unknown_overlay'].includes(e.type) ? ' (shadow mode)' : '';
    const score = e.score != null ? `<span class="muted">score ${Number(e.score).toFixed(2)}</span>` : '';
    const mediaHtml = [
      e.framePath ? `<a href="${media(e.framePath)}" target="_blank" rel="noopener"><img loading="lazy" src="${media(e.framePath)}" alt="Snapshot"></a>` : '',
      e.clipPath ? `<video controls preload="none" src="${media(e.clipPath)}"></video>` : '',
    ].join('');
    let actions = '';
    if (e.adminAction) {
      actions = `<span class="muted">${ACTION_TEXT[e.adminAction]}${e.resolvedAt ? ` · ${fmtTime(e.resolvedAt)}` : ''}</span>`;
    } else if (e.severity !== 'info') {
      actions = `<button data-resolve="confirm" data-event="${e.id}" class="danger">Confirm</button>
        <button data-resolve="fp" data-event="${e.id}">False positive</button>
        <button data-resolve="ignore" data-event="${e.id}">Ignore 10m</button>`;
    }
    return `<li class="ev">
      <div class="ev-head"><span class="pill ${sev[0]}">${sev[1]}</span><strong>${esc(RULE_TEXT[e.type] || e.type)}${shadow}</strong>
        <span class="muted">${fmtTime(e.ts)}</span>${score}</div>
      ${mediaHtml ? `<div class="ev-media">${mediaHtml}</div>` : ''}
      ${actions ? `<div class="ev-actions">${actions}</div>` : ''}
    </li>`;
  }

  async function watch() {
    if (room) return stopWatching();
    $('live').hidden = false;
    $('d-live-state').textContent = 'Connecting…';
    $('d-watch').textContent = 'Stop watching';
    const { url, token } = await api(`/admin/api/sessions/${openId}/watch`, { method: 'POST' });
    room = new Room({ adaptiveStream: false });
    room
      .on(RoomEvent.TrackSubscribed, (track) => {
        if (track.source !== Track.Source.Camera) return;
        track.attach($('d-video'));
        $('d-live-state').textContent = 'LIVE';
        $('d-live-state').className = 'pill live';
      })
      .on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach();
        $('d-live-state').textContent = 'Camera off';
        $('d-live-state').className = 'pill';
      })
      .on(RoomEvent.Disconnected, () => { $('d-live-state').textContent = 'Disconnected'; });
    await room.connect(url, token);
    if (!room.remoteParticipants.size) $('d-live-state').textContent = 'Waiting for player';
  }

  function stopWatching() {
    room?.disconnect();
    room = null;
    $('live').hidden = true;
    $('d-watch').textContent = 'Watch live';
  }

  // --- wiring -------------------------------------------------------------------------------

  $('grid').addEventListener('click', (e) => {
    const card = e.target.closest('.card');
    if (card) openDetail(Number(card.dataset.id));
  });
  $('close').addEventListener('click', closeDetail);
  document.addEventListener('keydown', (e) => e.key === 'Escape' && !$('detail').hidden && closeDetail());
  $('d-watch').addEventListener('click', () => watch().catch((err) => { $('d-live-state').textContent = err.message; }));
  $('d-stop').addEventListener('click', async () => {
    if (!confirm(`End ${$('d-name').textContent}'s hand cam session? Their cam disconnects.`)) return;
    await api(`/admin/api/sessions/${openId}/stop`, { method: 'POST' });
    stopWatching();
    await Promise.all([loadDetail(), loadSessions()]);
  });
  $('show-info').addEventListener('change', loadDetail);
  $('timeline').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-resolve]');
    if (!btn) return;
    for (const b of btn.parentElement.querySelectorAll('button')) b.disabled = true;
    await api(`/admin/api/events/${btn.dataset.event}/resolve`, { method: 'POST', body: JSON.stringify({ action: btn.dataset.resolve }) });
    await Promise.all([loadDetail(), loadSessions()]);
  });
  $('guild').addEventListener('change', (e) => {
    guild = e.target.value;
    store.set('hc_guild', guild);
    closeDetail();
    loadSessions();
  });

  async function start() {
    me = await api('/admin/api/me');
    if (!me) return;
    $('login').hidden = true;
    $('top').hidden = false;
    $('grid-wrap').hidden = false;
    $('me').textContent = me.name;
    const saved = store.get('hc_guild');
    guild = me.guilds.some((g) => g.id === saved) ? saved : me.guilds[0].id;
    $('guild').innerHTML = me.guilds.map((g) => `<option value="${g.id}">${esc(g.name)}</option>`).join('');
    $('guild').value = guild;
    $('guild').hidden = me.guilds.length < 2;
    await loadSessions();

    // Live updates; the 15 s poll covers a dropped socket.
    const socket = io({ path: '/admin/socket' });
    socket.on('session', () => loadSessions());
    socket.on('event', (m) => {
      loadSessions();
      if (m.sessionId === openId) loadDetail();
    });
    setInterval(loadSessions, 15_000);
  }

  start().catch((err) => console.error(err));
})();
