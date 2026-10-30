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
  const ACTION_TEXT = { confirmed: 'Confirmed', false_positive: 'False positive', ignored: 'Ignored 10 min' };
  const icon = (name) => `<svg><use href="#i-${name}"/></svg>`;
  const ti = (name) => `<svg class="i"><use href="/art/icons.svg#ti-${name}"/></svg>`;
  const PAGES = {
    all: ['Overview', 'All hand cams in this server.'],
    live: ['Live', 'Cams streaming right now.'],
    flagged: ['Flagged', 'Players with open warnings or violations. Review these first.'],
    pending: ['Waiting', 'Cam links sent but not opened yet.'],
    ended: ['Ended', 'Sessions from the last 24 hours.'],
  };

  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  let me = null;
  let guild = null;
  let sessions = [];
  let openId = null;
  let room = null;
  let filter = 'all';
  let query = '';

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
    for (const id of ['app', 'top', 'grid-wrap', 'detail', 'scrim']) $(id).hidden = true;
    $('login').hidden = false;
    return null;
  }

  const plural = (n, word) => `${n} ${word}${n == 1 ? '' : 's'}`;

  // Status chip + card outline for a session.
  function badge(s) {
    if (s.status === 'ended') return { cls: '', text: 'Ended', card: '' };
    if (s.status === 'pending') return { cls: '', text: 'Waiting', card: '' };
    if (Number(s.openViolations)) return { cls: 'chip-bad', text: plural(s.openViolations, 'violation'), card: 'violation' };
    if (s.status === 'stale') return { cls: 'chip-warn', text: 'Not checked', card: 'warning' };
    if (Number(s.openWarnings)) return { cls: 'chip-warn', text: plural(s.openWarnings, 'warning'), card: 'warning' };
    return { cls: 'chip-ok', text: 'Clean', card: '' };
  }

  const FILTERS = {
    all: () => true,
    live: (s) => s.status === 'live' || s.status === 'stale',
    flagged: (s) => s.status !== 'ended' && (Number(s.openViolations) || Number(s.openWarnings)),
    pending: (s) => s.status === 'pending',
    ended: (s) => s.status === 'ended',
  };

  // --- grid ---------------------------------------------------------------------------------

  async function loadSessions() {
    if (!guild) return;
    const body = await api(`/admin/api/sessions?guild=${guild}`);
    if (!body) return;
    sessions = body.sessions;
    renderGrid();
  }

  function renderGrid() {
    const count = (f) => sessions.filter(FILTERS[f]).length;
    const live = sessions.filter((s) => s.status === 'live').length;
    const flagged = sessions.filter((s) => s.status !== 'ended' && Number(s.openViolations)).length;
    const waiting = count('pending');
    const alerts = sessions.reduce((n, s) => n + Number(s.alerts || 0), 0);
    const kpi = (cls, iconName, label, value, note) =>
      `<div class="kpi ${cls}"><div class="kpi-top"><span class="label">${label}</span>${ti(iconName)}</div>` +
      `<b class="num">${value}</b><span class="kpi-note">${note}</span></div>`;
    $('counts').innerHTML =
      kpi('live', 'broadcast', 'Live now', live, live ? 'Streaming to the AI' : 'No cams streaming') +
      kpi(flagged ? 'bad' : '', 'alert-triangle', 'Flagged', flagged, flagged ? 'Open violations to review' : 'Nothing to review') +
      kpi('', 'hourglass', 'Waiting', waiting, 'Links not opened yet') +
      kpi('', 'flag', 'Alerts', alerts, 'Across listed sessions');
    $('page-title').textContent = PAGES[filter][0];
    $('page-sub').textContent = PAGES[filter][1];
    for (const tab of document.querySelectorAll('.tab')) {
      tab.classList.toggle('active', tab.dataset.filter === filter);
      tab.querySelector('span').textContent = count(tab.dataset.filter);
    }

    // Problems first, then live, waiting, ended.
    const rank = (s) => (s.status === 'ended' ? 4 : s.status === 'pending' ? 3 : Number(s.openViolations) ? 0 : Number(s.openWarnings) || s.status === 'stale' ? 1 : 2);
    const q = query.trim().toLowerCase();
    const matches = (s) => !q || `${playerName(s)} ${s.matchLabel ?? ''} ${s.discordUserId}`.toLowerCase().includes(q);
    const shown = sessions.filter((s) => FILTERS[filter](s) && matches(s)).sort((a, b) => rank(a) - rank(b) || b.id - a.id);
    $('empty').hidden = shown.length > 0;
    $('grid').innerHTML = shown.map((s) => {
      const b = badge(s);
      const since = s.startedAt ? fmtDur((Date.now() - new Date(s.startedAt)) / 1000) : '—';
      const watching = s.status === 'live' || s.status === 'stale';
      const thumb = watching
        ? `<img data-thumb="${s.id}" alt="" src="/admin/api/sessions/${s.id}/thumb.jpg?t=${Date.now()}">`
        : `<span class="placeholder">${icon(s.status === 'pending' ? 'clock' : 'flag')}${s.status === 'pending' ? 'Link not opened yet' : 'Session ended'}</span>`;
      const when = { ended: 'Ended', pending: 'Waiting' }[s.status] ?? since;
      return `<button class="card ${b.card}${watching ? '' : ' compact'}" data-id="${s.id}">
        <div class="thumb">${thumb}${watching ? '<div class="brackets"><i></i><i></i><i></i><i></i></div>' : ''}
          ${s.status === 'live' ? '<span class="chip chip-live"><span class="dot"></span>Live</span>' : ''}</div>
        <div class="card-body">
          <div class="card-title"><span>${esc(playerName(s))}</span><span class="chip ${b.cls}">${b.text}</span></div>
          <div class="card-meta">
            <span>${esc(s.matchLabel || 'No match label')}</span>
            <span>${icon('clock')}${when}</span>
            <span>${icon('flag')}${plural(s.alerts, 'alert')}</span>
          </div>
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
    $('scrim').hidden = false;
    $('live').hidden = true;
    await loadDetail();
  }

  function closeDetail() {
    openId = null;
    $('detail').hidden = true;
    $('scrim').hidden = true;
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
    $('d-meta').innerHTML = [
      s.status === 'live' ? '<span class="chip chip-live"><span class="dot"></span>Live</span>' : '',
      `<span class="chip ${b.cls}">${b.text}</span>`,
      s.matchLabel ? `<span>${esc(s.matchLabel)}</span>` : '',
      `<span>${icon('clock')}${up}</span>`,
      `<span>${icon('signal')}${(Number(s.dataBytes) / 1e6).toFixed(0)} MB</span>`,
      `<span class="num">ID ${esc(s.discordUserId)}</span>`,
    ].join('');
    const active = s.status !== 'ended';
    $('d-watch').hidden = !active;
    $('d-stop').hidden = !active;

    const showInfo = $('show-info').checked;
    const shown = events.filter((e) => showInfo || e.severity !== 'info');
    $('timeline').innerHTML = shown.length ? shown.map(eventRow).join('') : '<li class="none">No alerts. Clean so far.</li>';
    $('recordings').innerHTML = recordings.length
      ? recordings.map((r) => `<li>${icon('film')}<a href="${media(r.path)}" target="_blank" rel="noopener">${fmtTime(r.startedAt)} – ${r.endedAt ? fmtTime(r.endedAt) : 'recording now'}</a>
          ${r.keep ? '<span class="chip chip-warn">Kept · unresolved</span>' : ''}<span class="size">${(Number(r.sizeBytes) / 1e6).toFixed(1)} MB</span></li>`).join('')
      : '<li class="none">No recordings yet.</li>';
  }

  function eventRow(e) {
    const sev = e.severity === 'violation' ? ['chip-bad', 'Violation'] : e.severity === 'warning' ? ['chip-warn', 'Warning'] : ['', 'Info'];
    const shadow = e.severity === 'info' && ['mod_menu', 'esp_overlay', 'unknown_overlay'].includes(e.type);
    const score = e.score != null ? `<span class="score">score ${Number(e.score).toFixed(2)}</span>` : '';
    // One media slot: the clip with the snapshot as its cover, or just the snapshot until the clip is cut.
    const poster = e.framePath ? ` poster="${media(e.framePath)}"` : '';
    const mediaHtml = e.clipPath
      ? `<video controls preload="none"${poster} src="${media(e.clipPath)}"></video>`
      : e.framePath
        ? `<a href="${media(e.framePath)}" target="_blank" rel="noopener"><img loading="lazy" src="${media(e.framePath)}" alt="Snapshot"></a>`
        : '';
    let actions = '';
    if (e.adminAction) {
      actions = `<span class="resolved-by">${icon('check')}${ACTION_TEXT[e.adminAction]}${e.resolvedAt ? ` · ${fmtTime(e.resolvedAt)}` : ''}</span>`;
    } else if (e.severity !== 'info') {
      actions = `<button data-resolve="confirm" data-event="${e.id}" class="btn btn-danger">Confirm</button>
        <button data-resolve="fp" data-event="${e.id}" class="btn btn-ok">False positive</button>
        <button data-resolve="ignore" data-event="${e.id}" class="btn btn-ghost">Ignore 10m</button>`;
    }
    return `<li class="ev ${e.severity}${e.adminAction ? ' resolved' : ''}">
      <div class="ev-head"><span class="chip ${sev[0]}">${sev[1]}</span>${shadow ? '<span class="chip">Shadow</span>' : ''}
        <strong>${esc(RULE_TEXT[e.type] || e.type)}</strong>${score}<span class="time">${fmtTime(e.ts)}</span></div>
      ${mediaHtml ? `<div class="ev-media">${mediaHtml}</div>` : ''}
      ${e.llmVerdict ? `<div class="ev-verdict">${icon('bot')}<span>AI second opinion: ${esc(e.llmVerdict)}</span></div>` : ''}
      ${actions ? `<div class="ev-actions">${actions}</div>` : ''}
    </li>`;
  }

  async function watch() {
    if (room) return stopWatching();
    $('live').hidden = false;
    $('d-live-state').textContent = 'Connecting…';
    $('d-live-state').className = 'chip';
    $('d-watch').querySelector('span').textContent = 'Stop watching';
    const { url, token } = await api(`/admin/api/sessions/${openId}/watch`, { method: 'POST' });
    room = new Room({ adaptiveStream: false });
    room
      .on(RoomEvent.TrackSubscribed, (track) => {
        if (track.source !== Track.Source.Camera) return;
        track.attach($('d-video'));
        $('d-live-state').textContent = 'LIVE';
        $('d-live-state').className = 'chip chip-live';
      })
      .on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach();
        $('d-live-state').textContent = 'Camera off';
        $('d-live-state').className = 'chip chip-warn';
      })
      .on(RoomEvent.Disconnected, () => { $('d-live-state').textContent = 'Disconnected'; });
    await room.connect(url, token);
    if (!room.remoteParticipants.size) $('d-live-state').textContent = 'Waiting for player';
  }

  function stopWatching() {
    room?.disconnect();
    room = null;
    $('live').hidden = true;
    $('d-watch').querySelector('span').textContent = 'Watch live';
  }

  // --- wiring -------------------------------------------------------------------------------

  $('grid').addEventListener('click', (e) => {
    const card = e.target.closest('.card');
    if (card) openDetail(Number(card.dataset.id));
  });
  $('close').addEventListener('click', closeDetail);
  $('scrim').addEventListener('click', closeDetail);
  $('search').addEventListener('input', (e) => {
    query = e.target.value;
    renderGrid();
  });
  $('tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (!tab) return;
    filter = tab.dataset.filter;
    renderGrid();
  });
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
    $('app').hidden = false;
    $('top').hidden = false;
    $('grid-wrap').hidden = false;
    $('me').textContent = me.name;
    $('avatar').textContent = (me.name || '?').trim().charAt(0).toUpperCase();
    const saved = store.get('hc_guild');
    guild = me.guilds.some((g) => g.id === saved) ? saved : me.guilds[0].id;
    $('guild').innerHTML = me.guilds.map((g) => `<option value="${g.id}">${esc(g.name)}</option>`).join('');
    $('guild').value = guild;
    $('guild').disabled = me.guilds.length < 2;
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
