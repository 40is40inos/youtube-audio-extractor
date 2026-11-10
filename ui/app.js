'use strict';

(() => {
  const $ = (id) => document.getElementById(id);

  const EASE_OUT = 'cubic-bezier(0.23, 1, 0.32, 1)';
  const EASE_IN_OUT = 'cubic-bezier(0.77, 0, 0.175, 1)';
  const motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
  let reduced = motionQuery.matches;

  // Tonearm angles in degrees, worked out from the turntable geometry in app.css:
  // parked beside the platter, over the lead-in groove, and over the run-out groove.
  const ARM = { boot: -9, rest: 0, start: 15.5, end: 33.5 };
  const SPIN = 200; // 33⅓ rpm, in degrees per second

  const FORMAT_HINTS = {
    mp3: 'Plays on everything. Re-encoded, so slightly lossy.',
    opus: 'YouTube’s own audio, usually copied as is. Smallest files.',
    m4a: 'AAC in an MP4 wrapper. A good pick for Apple devices.',
    flac: 'Lossless wrapper. Bigger, but no better than the source.',
    wav: 'Uncompressed. Huge files, handy for audio editors.',
    aac: 'Raw AAC stream. Small and widely supported.',
    best: 'Whatever YouTube serves, with no conversion at all.',
  };

  const ERRORS = {
    http403: 'YouTube refused the download (HTTP 403). Update yt-dlp and try again. If it keeps happening, refresh your cookies or switch networks.',
    signin: 'YouTube wants a signed-in session for this video. Pick a cookies source and try again.',
    cookies_browser: 'Couldn’t read that browser’s cookies. Close the browser completely, or use Firefox or a cookies.txt file.',
    unavailable: 'This video is unavailable: private, removed, or blocked in your region.',
    unsupported: 'yt-dlp doesn’t recognise this link.',
    ffmpeg: 'ffmpeg.exe is missing, so the audio couldn’t be converted.',
    folder: 'Couldn’t create the save folder.',
    ytdlp_missing: 'yt-dlp.exe wasn’t found next to the app.',
  };

  const ICONS = {
    play: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path class="fill" d="M5 3.2v9.6c0 .5.5.8.9.5l7.2-4.8a.6.6 0 0 0 0-1L5.9 2.7c-.4-.3-.9 0-.9.5z"/></svg>',
    folder: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4.5c0-.6.4-1 1-1h3l1.5 1.5H13c.6 0 1 .4 1 1V12c0 .6-.4 1-1 1H3c-.6 0-1-.4-1-1z"/></svg>',
    close: '<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>',
  };

  // ------------------------------------------------------------------ token + api

  const TOKEN = (() => {
    const match = location.hash.match(/t=([\w-]+)/);
    if (match) {
      try { sessionStorage.setItem('extractor:t', match[1]); } catch { /* storage blocked */ }
      history.replaceState(null, '', location.pathname);
      return match[1];
    }
    try { return sessionStorage.getItem('extractor:t') || ''; } catch { return ''; }
  })();

  async function api(path, body) {
    const init = { method: body === undefined ? 'GET' : 'POST', headers: { 'X-Token': TOKEN } };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch { /* empty body */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  // ------------------------------------------------------------------ dom + state

  const el = {
    app: $('app'), disc: $('disc'), record: $('record'), label: $('label'), labelImg: $('labelImg'),
    arm: $('arm'), armShadow: $('armShadow'), ringFill: $('ringFill'), ambA: $('ambA'), ambB: $('ambB'),
    stageText: $('stageText'), title: $('title'), sub: $('sub'), pct: $('pct'), metricLine: $('metricLine'),
    playBtn: $('playBtn'), revealBtn: $('revealBtn'),
    fields: $('fields'), url: $('url'), urlWrap: $('urlWrap'), pasteBtn: $('pasteBtn'),
    clip: $('clip'), clipText: $('clipText'), clipUse: $('clipUse'), clipDismiss: $('clipDismiss'),
    seg: $('seg'), segInd: $('segInd'), fmtHint: $('fmtHint'), folder: $('folder'), browseBtn: $('browseBtn'),
    cookies: $('cookies'), fname: $('fname'), go: $('go'), goLabel: $('goLabel'), notices: $('notices'),
    recent: $('recent'), recentCount: $('recentCount'),
    ver: $('ver'), verText: $('verText'), updateBtn: $('updateBtn'), updateText: $('updateText'),
    logToggle: $('logToggle'), logCount: $('logCount'), lastLine: $('lastLine'),
    drawer: $('drawer'), log: $('log'), copyLog: $('copyLog'), closeLog: $('closeLog'),
  };

  const S = {
    booted: false,
    formats: [],
    format: 'mp3',
    preview: null,
    previewFor: '',
    previewLoading: false,
    previewSeq: 0,
    labelSrc: null,
    ambientSrc: null,
    job: null,
    ackId: null,
    update: null,
    starting: false,
    finishedAt: 0,
    stopArmed: false,
    logSeq: 0,
    logCount: 0,
    version: null,
    notices: [],
    clipUrl: null,
    clipDismissed: '',
  };

  // ------------------------------------------------------------------ small helpers

  function normalizeUrl(raw) {
    const text = (raw || '').trim();
    if (!text || /\s/.test(text)) return '';
    const withScheme = /^https?:\/\//i.test(text) ? text : `https://${text}`;
    try {
      const url = new URL(withScheme);
      return url.hostname.includes('.') ? url.href : '';
    } catch {
      return '';
    }
  }

  function hostOf(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
  }

  function prettyUrl(url) {
    try {
      const u = new URL(url);
      const text = u.hostname.replace(/^www\./, '') + u.pathname.replace(/\/$/, '') + u.search;
      return text.length > 48 ? `${text.slice(0, 47)}…` : text;
    } catch {
      return url;
    }
  }

  function baseName(path) {
    const name = (path || '').split(/[\\/]/).pop() || '';
    return name.replace(/\.[^.]+$/, '');
  }

  function extOf(path) {
    const match = (path || '').match(/\.([^.\\/]+)$/);
    return match ? match[1] : '';
  }

  function fmtBytes(n) {
    if (n == null || !Number.isFinite(n)) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
  }

  function fmtEta(seconds) {
    const s = Math.max(0, Math.ceil(seconds));
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  function ago(ts) {
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
    return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

  function ageText(hours) {
    if (hours < 1) return 'fresh';
    if (hours < 48) return `${Math.round(hours)} h old`;
    return `${Math.round(hours / 24)} days old`;
  }

  function shortPath(path) {
    if (path.length <= 34) return path;
    const parts = path.split(/[\\/]/).filter(Boolean);
    return `…\\${parts.slice(-2).join('\\')}`;
  }

  function nudge(node) {
    if (reduced) return;
    node.animate(
      [
        { transform: 'translateX(0)' },
        { transform: 'translateX(-5px)' },
        { transform: 'translateX(4px)' },
        { transform: 'translateX(-2px)' },
        { transform: 'translateX(0)' },
      ],
      { duration: 320, easing: 'ease-out' },
    );
  }

  // Crossfade a text change: the old words blur out quickly, the new ones settle in.
  function swapText(node, text, instant = false) {
    const current = node.dataset.text ?? node.textContent;
    if (current === text) return;
    node.dataset.text = text;
    node.getAnimations().forEach((a) => a.cancel());
    if (instant || reduced || !node.textContent) {
      node.textContent = text;
      return;
    }
    const out = node.animate(
      [{ opacity: 1, filter: 'blur(0)' }, { opacity: 0, transform: 'translateY(-3px)', filter: 'blur(2px)' }],
      { duration: 110, easing: 'ease' },
    );
    out.onfinish = () => {
      if (node.dataset.text !== text) return;
      node.textContent = text;
      node.animate(
        [{ opacity: 0, transform: 'translateY(4px)', filter: 'blur(2px)' }, { opacity: 1, transform: 'none', filter: 'blur(0)' }],
        { duration: 240, easing: EASE_OUT },
      );
    };
  }

  // ------------------------------------------------------------------ motion engine

  // A spring described the way Apple does: response (seconds) and damping ratio (1 = no overshoot).
  class Spring {
    constructor(value, response, damping = 1) {
      this.x = value;
      this.v = 0;
      this.target = value;
      this.k = (2 * Math.PI / response) ** 2;
      this.c = (4 * Math.PI * damping) / response;
    }

    step(dt) {
      let left = dt;
      while (left > 0) {
        const h = Math.min(left, 1 / 240);
        const a = -this.k * (this.x - this.target) - this.c * this.v;
        this.v += a * h;
        this.x += this.v * h;
        left -= h;
      }
    }

    snap() { this.x = this.target; this.v = 0; }

    get settled() { return Math.abs(this.x - this.target) < 0.01 && Math.abs(this.v) < 0.01; }
  }

  // One rAF loop drives the platter, the tonearm and the progress ring, and stops when all are at rest.
  const engine = {
    angle: 0,
    omega: 0,
    omegaTarget: 0,
    arm: new Spring(ARM.boot, 0.6),
    lift: new Spring(0, 0.22),
    ring: new Spring(0, 0.3),
    pctShown: -1,
    raf: 0,
    last: 0,

    kick() {
      if (this.raf) return;
      this.last = performance.now();
      this.raf = requestAnimationFrame((t) => this.frame(t));
    },

    frame(t) {
      const dt = Math.min(0.05, (t - this.last) / 1000);
      this.last = t;
      // Motor torque spins up a little quicker than friction spins down.
      const tau = this.omegaTarget > this.omega ? 0.45 : 0.6;
      this.omega += (this.omegaTarget - this.omega) * (1 - Math.exp(-dt / tau));
      if (this.omegaTarget === 0 && this.omega < 0.6) this.omega = 0;
      this.angle = (this.angle + this.omega * dt) % 360;
      for (const spring of [this.arm, this.lift, this.ring]) {
        if (reduced) spring.snap();
        else spring.step(dt);
      }
      this.render();
      const moving = this.omega !== 0 || this.omegaTarget !== 0
        || !this.arm.settled || !this.lift.settled || !this.ring.settled;
      this.raf = moving ? requestAnimationFrame((tt) => this.frame(tt)) : 0;
    },

    render() {
      el.record.style.transform = `rotate(${this.angle.toFixed(2)}deg)`;
      const lift = this.lift.x;
      const turn = `rotate(${this.arm.x.toFixed(3)}deg)`;
      el.arm.style.transform = `${turn} scale(${(1 + lift * 0.022).toFixed(4)})`;
      el.armShadow.style.transform = `translate(${(4 + lift * 10).toFixed(2)}px, ${(6 + lift * 14).toFixed(2)}px) ${turn}`;
      el.armShadow.style.opacity = (0.5 - lift * 0.18).toFixed(3);
      const p = Math.min(100, Math.max(0, this.ring.x));
      el.ringFill.style.strokeDashoffset = (100 - p).toFixed(2);
      const shown = Math.floor(p + 0.001);
      if (shown !== this.pctShown) {
        this.pctShown = shown;
        el.pct.textContent = String(shown);
        if (S.job && S.job.status === 'running' && S.job.stage !== 'resolving') document.title = `${shown}% · Extractor`;
      }
    },
  };

  engine.arm.target = ARM.rest; // first frame swings it in from the boot angle

  let armTimers = [];
  let parking = false;

  function clearArmTimers() {
    armTimers.forEach(clearTimeout);
    armTimers = [];
    parking = false;
  }

  // Lift, swing home, then set down, like the real thing.
  function parkArm() {
    if (parking || (engine.arm.target === ARM.rest && engine.lift.target === 0)) return;
    parking = true;
    engine.lift.target = 1;
    armTimers.push(setTimeout(() => { engine.arm.target = ARM.rest; engine.kick(); }, reduced ? 0 : 170));
    armTimers.push(setTimeout(() => { engine.lift.target = 0; parking = false; engine.kick(); }, reduced ? 0 : 900));
  }

  function applyMotion() {
    const job = S.job;
    if (el.app.dataset.state === 'running') {
      clearArmTimers();
      engine.omegaTarget = reduced ? 0 : SPIN;
      if (job.stage === 'resolving') {
        engine.arm.target = ARM.start - 2;
        engine.lift.target = 1;
        engine.ring.target = 0;
      } else if (job.stage === 'downloading') {
        const p = job.progress == null ? 0 : job.progress;
        engine.arm.target = ARM.start + ((ARM.end - ARM.start) * p) / 100;
        engine.lift.target = 0;
        engine.ring.target = p;
      } else {
        engine.arm.target = ARM.end;
        engine.lift.target = 0;
        engine.ring.target = 100;
      }
    } else {
      engine.omegaTarget = 0;
      if (el.app.dataset.state === 'done') engine.ring.target = 100;
      parkArm();
    }
    engine.kick();
  }

  // ------------------------------------------------------------------ deck: label + ambient

  function loadImage(src) {
    return new Promise((resolve) => {
      if (!src) { resolve(null); return; }
      const img = new Image();
      img.referrerPolicy = 'no-referrer';
      img.onload = () => resolve(img.naturalWidth > 200 ? src : null);
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  let ambFront = null;
  function setAmbient(src) {
    if (src === S.ambientSrc) return;
    S.ambientSrc = src;
    if (!src) {
      el.ambA.removeAttribute('data-on');
      el.ambB.removeAttribute('data-on');
      return;
    }
    const back = ambFront === el.ambA ? el.ambB : el.ambA;
    back.onload = () => {
      if (S.ambientSrc !== src) return;
      back.dataset.on = '';
      if (ambFront && ambFront !== back) ambFront.removeAttribute('data-on');
      ambFront = back;
    };
    back.src = src;
  }

  // A new record is set on the platter: it drops in from just above, the art sharpens into place.
  function setLabel(src, ambient) {
    if (src === S.labelSrc) return;
    S.labelSrc = src;
    setAmbient(ambient || src);
    if (src) {
      el.labelImg.src = src;
      el.label.dataset.hasImg = '';
    } else {
      el.label.removeAttribute('data-has-img');
    }
    if (reduced || !S.booted) return;
    el.disc.animate(
      [{ transform: 'translateY(-10px) scale(1.025)', opacity: 0.8 }, { transform: 'none', opacity: 1 }],
      { duration: 520, easing: EASE_OUT },
    );
    if (src) {
      el.labelImg.animate(
        [{ opacity: 0, transform: 'scale(1.08)', filter: 'blur(6px)' }, { opacity: 1, transform: 'none', filter: 'blur(0)' }],
        { duration: 460, easing: EASE_OUT },
      );
    }
  }

  // ------------------------------------------------------------------ rendering

  function previewTitle(p) {
    return p.title || (p.kind === 'youtube' ? 'YouTube video' : p.host || 'Your link');
  }

  function jobTitle(job) {
    if (job.title) return job.title;
    if (S.preview && S.previewFor === job.url) return previewTitle(S.preview);
    return hostOf(job.url) || 'Your link';
  }

  function errorText(job) {
    if (ERRORS[job.error]) return ERRORS[job.error];
    if (job.detail) return job.detail.length > 170 ? `${job.detail.slice(0, 169)}…` : job.detail;
    return 'Something went wrong. Open the log for details.';
  }

  function viewOf() {
    const job = S.job;
    if (job && job.status === 'running') return 'running';
    if (job && job.id !== S.ackId) return job.status;
    if (S.previewLoading && !S.preview) return 'loading';
    if (S.preview) return 'ready';
    return 'empty';
  }

  function metricText(job, fmt) {
    if (job.stage === 'resolving') return 'Contacting YouTube…';
    if (job.stage === 'converting') return `ffmpeg is writing the ${fmt} file…`;
    const parts = [];
    if (job.total) parts.push(job.downloaded != null ? `${fmtBytes(job.downloaded)} of ${fmtBytes(job.total)}` : fmtBytes(job.total));
    if (job.speed) parts.push(`${fmtBytes(job.speed)}/s`);
    if (job.eta != null && (job.progress == null || job.progress < 100)) parts.push(`${fmtEta(job.eta)} left`);
    return parts.join('  ·  ') || 'Downloading…';
  }

  function render() {
    const view = viewOf();
    const job = S.job;
    const running = view === 'running';
    el.app.dataset.state = view;
    el.app.dataset.stage = running ? job.stage : '';
    el.fields.disabled = running || Boolean(S.update && S.update.status === 'running');

    const fmt = ((job && (extOf(job.file) || job.format)) || S.format).toUpperCase();
    let stage = 'Ready';
    let title = 'Paste a YouTube link';
    let sub = 'Press Ctrl+V anywhere, or use the link field.';
    let slot = 'sub';

    if (view === 'loading') {
      stage = 'Looking up';
      title = 'Reading the link…';
      sub = hostOf(S.previewFor);
    } else if (view === 'ready') {
      const p = S.preview;
      stage = 'Ready to extract';
      title = previewTitle(p);
      sub = p.author || (p.kind === 'other' ? 'The title shows up once the download starts.' : '');
    } else if (running) {
      stage = { resolving: 'Fetching info', downloading: 'Downloading', converting: `Converting to ${fmt}` }[job.stage] || 'Working';
      title = jobTitle(job);
      slot = 'metrics';
      el.metricLine.textContent = metricText(job, fmt);
    } else if (view === 'done') {
      stage = job.size ? `Saved · ${fmt} · ${fmtBytes(job.size)}` : 'Saved';
      title = job.file ? baseName(job.file) : jobTitle(job);
      slot = job.file ? 'result' : 'sub';
      sub = 'Finished, but the saved file couldn’t be located. Check the log.';
    } else if (view === 'failed') {
      stage = 'Failed';
      title = jobTitle(job);
      sub = errorText(job);
    } else if (view === 'stopped') {
      stage = 'Stopped';
      title = jobTitle(job);
      sub = 'Stopped before it finished. Nothing was saved.';
    }

    el.app.dataset.slot = slot;
    swapText(el.stageText, stage);
    swapText(el.title, title);
    swapText(el.sub, sub);
    if (!running) document.title = view === 'done' ? 'Saved · Extractor' : 'Extractor';
    renderButton();
    renderUpdate();
    applyMotion();
  }

  function renderButton() {
    const running = S.job && S.job.status === 'running';
    const updating = S.update && S.update.status === 'running';
    const mode = running ? (S.stopArmed ? 'confirm' : 'stop') : 'extract';
    el.go.dataset.mode = mode;
    el.go.disabled = Boolean(updating && !running);
    let label = 'Extract audio';
    if (mode === 'stop') label = 'Stop';
    else if (mode === 'confirm') label = 'Click again to stop';
    else if (updating) label = 'Updating yt-dlp…';
    swapText(el.goLabel, label);
  }

  function renderUpdate() {
    const updating = Boolean(S.update && S.update.status === 'running');
    el.app.toggleAttribute('data-updating', updating);
    el.updateBtn.disabled = updating || Boolean(S.job && S.job.status === 'running');
    el.updateText.textContent = updating ? 'Updating…' : 'Update yt-dlp';
  }

  function renderVersion() {
    const v = S.version || {};
    let health = 'unknown';
    let text = 'yt-dlp';
    if (v.found === false) {
      health = 'missing';
      text = 'yt-dlp.exe not found';
    } else if (v.version) {
      const old = v.age_days != null && v.age_days > 60;
      health = old ? 'old' : 'ok';
      text = old ? `yt-dlp ${v.version} · ${v.age_days} days old` : `yt-dlp ${v.version}`;
    }
    el.ver.dataset.health = health;
    el.verText.textContent = text;
    el.ver.title = v.age_days != null ? `Released ${v.age_days} days ago${v.age_days > 60 ? ': update recommended' : ''}` : '';
  }

  // ------------------------------------------------------------------ jobs

  function setJob(job, silent = false) {
    if (!job) return;
    if (job.kind === 'update') {
      S.update = job;
      render();
      return;
    }
    const prev = S.job;
    S.job = job;
    if (job.status !== 'running') {
      S.stopArmed = false;
      clearTimeout(stopTimer);
      if (prev && prev.id === job.id && prev.status === 'running') S.finishedAt = Date.now();
    }
    const justFinished = !silent && prev && prev.id === job.id && prev.status === 'running';
    render();
    if (justFinished && job.status === 'done' && job.history_item) celebrate(job.history_item);
  }

  let stopTimer = 0;
  async function onGo() {
    if (S.job && S.job.status === 'running') {
      if (!S.stopArmed) {
        S.stopArmed = true;
        renderButton();
        clearTimeout(stopTimer);
        stopTimer = setTimeout(() => { S.stopArmed = false; renderButton(); }, 2600);
        return;
      }
      S.stopArmed = false;
      clearTimeout(stopTimer);
      renderButton();
      try { await api('/api/stop', {}); } catch { /* the job event reports the outcome */ }
      return;
    }
    // The button turns from Stop back into Extract at the same spot. A Stop click that lands
    // just after the run finished must not start a new one.
    if (Date.now() - S.finishedAt < 900) return;
    startExtract();
  }

  async function startExtract() {
    if (S.starting || (S.job && S.job.status === 'running') || (S.update && S.update.status === 'running')) return;
    const url = normalizeUrl(el.url.value);
    if (!url) {
      nudge(el.urlWrap);
      el.url.focus();
      return;
    }
    if (S.job) S.ackId = S.job.id;
    clearNotices();
    const p = S.preview && S.previewFor === url ? S.preview : null;
    S.starting = true;
    try {
      const { job } = await api('/api/extract', {
        url,
        format: S.format,
        folder: el.folder.value,
        cookies: el.cookies.value,
        filename: el.fname.value,
        title: p ? p.title : null,
        author: p ? p.author : null,
        thumb: p && p.kind === 'youtube' ? S.labelSrc : null,
      });
      if (!S.job || S.job.id !== job.id) setJob(job);
    } catch (err) {
      let text = 'Couldn’t start the extraction.';
      if (err.status === 409) text = 'Something is already running. Wait for it, or stop it first.';
      if (err.status === 400) text = 'That link or folder doesn’t look right.';
      addNotice({ level: 'error', code: 'start', text });
      render();
    } finally {
      S.starting = false;
    }
  }

  // ------------------------------------------------------------------ link + preview

  async function loadPreview(raw) {
    const url = normalizeUrl(raw);
    if (url && url === S.previewFor && (S.preview || S.previewLoading)) return;
    const seq = ++S.previewSeq;
    if (!url) {
      S.preview = null;
      S.previewFor = '';
      S.previewLoading = false;
      setLabel(null);
      el.fname.placeholder = 'Uses the video title';
      render();
      return;
    }
    S.preview = null;
    S.previewFor = url;
    S.previewLoading = true;
    render();
    let data = null;
    try { data = await api('/api/preview', { url }); } catch { /* fall back to the bare link */ }
    if (seq !== S.previewSeq) return;
    S.previewLoading = false;
    S.preview = data || { kind: 'other', url, host: hostOf(url) };
    el.fname.placeholder = S.preview.title || 'Uses the video title';
    render();
    if (S.preview.kind === 'youtube') {
      const src = (await loadImage(S.preview.thumb)) || (await loadImage(S.preview.thumb_fallback));
      if (seq !== S.previewSeq) return;
      setLabel(src, S.preview.thumb_fallback);
    } else {
      setLabel(null);
    }
  }

  function onUrlEdited() {
    if (S.job && S.job.status !== 'running') S.ackId = S.job.id;
    if (S.clipUrl && normalizeUrl(el.url.value) === S.clipUrl) {
      S.clipUrl = null;
      renderClip();
    }
  }

  function setUrl(url) {
    el.url.value = url;
    S.clipUrl = null;
    renderClip();
    onUrlEdited();
    loadPreview(url);
  }

  async function readClipboard() {
    try {
      const { url } = await api('/api/clipboard', {});
      return url;
    } catch {
      return null;
    }
  }

  async function checkClipboard() {
    if (document.visibilityState !== 'visible' || !S.booted) return;
    const url = await readClipboard();
    const current = normalizeUrl(el.url.value);
    const busy = S.job && S.job.status === 'running';
    S.clipUrl = url && url !== current && url !== S.clipDismissed && !busy ? url : null;
    renderClip();
  }

  function renderClip() {
    const open = Boolean(S.clipUrl);
    el.clip.dataset.open = String(open);
    el.clipUse.tabIndex = open ? 0 : -1;
    el.clipDismiss.tabIndex = open ? 0 : -1;
    if (open) el.clipText.textContent = prettyUrl(S.clipUrl);
  }

  // ------------------------------------------------------------------ format picker

  function buildFormats(formats) {
    S.formats = formats;
    formats.forEach((fmt) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'radio');
      button.dataset.value = fmt;
      button.textContent = fmt;
      button.addEventListener('click', () => chooseFormat(fmt, false));
      el.seg.append(button);
    });
    el.seg.addEventListener('keydown', (e) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      const i = S.formats.indexOf(S.format);
      const next = S.formats[(i + step + S.formats.length) % S.formats.length];
      chooseFormat(next, true); // keyboard: no slide
      el.seg.querySelector(`[data-value="${next}"]`).focus();
    });
  }

  function chooseFormat(fmt, instant) {
    if (!S.formats.includes(fmt)) fmt = S.formats.includes('mp3') ? 'mp3' : S.formats[0];
    S.format = fmt;
    const buttons = [...el.seg.querySelectorAll('button')];
    const index = buttons.findIndex((b) => b.dataset.value === fmt);
    buttons.forEach((b, i) => {
      b.setAttribute('aria-checked', String(i === index));
      b.tabIndex = i === index ? 0 : -1;
    });
    if (instant || reduced) {
      el.segInd.style.transition = 'none';
      el.segInd.style.transform = `translateX(${index * 100}%)`;
      void el.segInd.offsetWidth;
      el.segInd.style.transition = '';
    } else {
      el.segInd.style.transform = `translateX(${index * 100}%)`;
    }
    swapText(el.fmtHint, FORMAT_HINTS[fmt] || '', instant);
    savePrefs();
  }

  // ------------------------------------------------------------------ selects + prefs

  function fillFolders(folders, selected) {
    el.folder.replaceChildren(...folders.map((f) => new Option(f.custom ? shortPath(f.label) : f.label, f.value)));
    if (selected && !folders.some((f) => f.value === selected)) el.folder.add(new Option(shortPath(selected), selected));
    el.folder.value = selected || (folders[0] && folders[0].value) || '';
    el.folder.title = el.folder.value;
  }

  function fillCookies(sources, selected) {
    el.cookies.replaceChildren(
      ...sources.map((c) => new Option(c.age_hours != null ? `${c.label} · ${ageText(c.age_hours)}` : c.label, c.value)),
    );
    el.cookies.value = sources.some((c) => c.value === selected) ? selected : 'none';
  }

  let prefsTimer = 0;
  function savePrefs() {
    if (!S.booted) return;
    clearTimeout(prefsTimer);
    prefsTimer = setTimeout(() => {
      api('/api/prefs', { format: S.format, folder: el.folder.value, cookies: el.cookies.value }).catch(() => {});
    }, 300);
  }

  // ------------------------------------------------------------------ recent list

  function openPath(path, action) {
    api('/api/open', { path, action }).catch(() => {});
  }

  function itemNode(item) {
    const li = document.createElement('li');
    li.className = 'item';
    li.dataset.file = item.file;
    li.title = item.file;
    if (item.missing) li.classList.add('missing');

    let thumb;
    if (item.thumb && item.thumb.startsWith('https://i.ytimg.com/')) {
      thumb = document.createElement('img');
      thumb.alt = '';
      thumb.loading = 'lazy';
      thumb.referrerPolicy = 'no-referrer';
      thumb.src = item.thumb;
    } else {
      thumb = document.createElement('span');
      thumb.classList.add('blank');
    }
    thumb.classList.add('item-thumb');

    const body = document.createElement('div');
    body.className = 'item-body';
    const title = document.createElement('div');
    title.className = 'item-title';
    title.textContent = item.title || baseName(item.file);
    const meta = document.createElement('div');
    meta.className = 'item-meta';
    const fmt = document.createElement('span');
    fmt.className = 'fmt';
    fmt.textContent = (item.format || extOf(item.file)).toUpperCase();
    const rest = [fmtBytes(item.size), item.missing ? 'file moved or deleted' : ago(item.ts)].filter(Boolean).join(' · ');
    meta.append(fmt, document.createTextNode(rest ? ` · ${rest}` : ''));
    body.append(title, meta);

    const actions = document.createElement('div');
    actions.className = 'item-actions';
    const play = document.createElement('button');
    play.type = 'button';
    play.className = 'icon-btn sm';
    play.setAttribute('aria-label', `Play ${title.textContent}`);
    play.innerHTML = ICONS.play;
    play.addEventListener('click', () => openPath(item.file, 'play'));
    const reveal = document.createElement('button');
    reveal.type = 'button';
    reveal.className = 'icon-btn sm';
    reveal.setAttribute('aria-label', `Show ${title.textContent} in its folder`);
    reveal.innerHTML = ICONS.folder;
    reveal.addEventListener('click', () => openPath(item.file, 'reveal'));
    actions.append(play, reveal);

    li.append(thumb, body, actions);
    li.addEventListener('click', (e) => {
      if (!e.target.closest('button') && !item.missing) openPath(item.file, 'reveal');
    });
    return li;
  }

  function renderRecent(items) {
    el.recent.replaceChildren(...items.map(itemNode));
    el.recentCount.textContent = items.length ? String(items.length) : '';
  }

  // The saved track peels off the record and flies into the list, which opens a slot for it.
  function celebrate(item) {
    setTimeout(() => insertRecent(item), reduced ? 0 : 420);
  }

  function insertRecent(item) {
    const list = el.recent;
    list.scrollTop = 0;
    [...list.children].forEach((li) => { if (li.dataset.file === item.file) li.remove(); });
    const before = new Map([...list.children].map((li) => [li, li.getBoundingClientRect().top]));
    const li = itemNode(item);
    list.prepend(li);
    while (list.children.length > 40) list.lastElementChild.remove();
    el.recentCount.textContent = String(list.children.length);

    if (reduced) {
      li.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 });
      return;
    }
    before.forEach((top, node) => {
      const dy = top - node.getBoundingClientRect().top;
      if (dy) node.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: 300, easing: EASE_OUT });
    });
    fly(li);
  }

  function fly(li) {
    const thumb = li.querySelector('.item-thumb');
    const body = li.querySelector('.item-body');
    const to = thumb.getBoundingClientRect();
    const disc = el.disc.getBoundingClientRect();
    const size = el.record.offsetWidth * 0.38;
    const listBox = el.recent.getBoundingClientRect();
    if (!to.width || !size || to.bottom > listBox.bottom + 1) {
      li.classList.add('flash');
      return;
    }
    const fromX = disc.left + disc.width / 2;
    const fromY = disc.top + disc.height / 2;
    const clone = document.createElement('div');
    clone.className = 'fly';
    if (S.labelSrc && el.label.hasAttribute('data-has-img')) {
      const img = new Image();
      img.alt = '';
      img.src = S.labelSrc;
      clone.append(img);
    } else {
      clone.classList.add('blank');
    }
    Object.assign(clone.style, {
      width: `${size}px`,
      height: `${size}px`,
      left: `${fromX - size / 2}px`,
      top: `${fromY - size / 2}px`,
    });
    document.body.append(clone);

    const scale = to.width / size;
    const dx = to.left + to.width / 2 - fromX;
    const dy = to.top + to.height / 2 - fromY;
    const angle = engine.angle % 360;
    thumb.style.opacity = '0';
    const flight = clone.animate(
      [
        { transform: `translate(0px, 0px) rotate(${angle}deg) scale(1)`, borderRadius: '50%' },
        { transform: `translate(${dx}px, ${dy}px) rotate(${angle > 180 ? 360 : 0}deg) scale(${scale})`, borderRadius: `${10 / scale}px` },
      ],
      { duration: 680, easing: EASE_IN_OUT, fill: 'forwards' },
    );
    body.animate(
      [{ opacity: 0, transform: 'translateX(-6px)' }, { opacity: 1, transform: 'none' }],
      { duration: 260, delay: 560, easing: EASE_OUT, fill: 'backwards' },
    );
    flight.finished.then(() => {
      thumb.style.opacity = '';
      clone.remove();
      li.classList.add('flash');
      setTimeout(() => li.classList.remove('flash'), 900);
    });
  }

  // ------------------------------------------------------------------ notices

  function addNotice(n) {
    const id = Math.random().toString(36).slice(2);
    S.notices = [...S.notices.filter((x) => x.code !== n.code), { ...n, id }].slice(-3);
    renderNotices();
    if (n.level === 'ok') setTimeout(() => dismissNotice(id), 6000);
  }

  function dismissNotice(id) {
    S.notices = S.notices.filter((n) => n.id !== id);
    renderNotices();
  }

  function clearNotices() {
    S.notices = S.notices.filter((n) => n.code === 'ffmpeg');
    renderNotices();
  }

  function renderNotices() {
    const keep = new Set(S.notices.map((n) => n.id));
    [...el.notices.children].forEach((node) => {
      if (keep.has(node.dataset.id) || node.hasAttribute('data-leaving')) return;
      node.dataset.leaving = '';
      setTimeout(() => node.remove(), 150);
    });
    S.notices.forEach((n) => {
      if (el.notices.querySelector(`[data-id="${n.id}"]`)) return;
      const node = document.createElement('div');
      node.className = 'notice';
      node.dataset.id = n.id;
      node.dataset.level = n.level || 'warn';
      const text = document.createElement('p');
      text.textContent = n.text;
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'icon-btn sm';
      close.setAttribute('aria-label', 'Dismiss');
      close.innerHTML = ICONS.close;
      close.addEventListener('click', () => dismissNotice(n.id));
      node.append(text, close);
      el.notices.append(node);
    });
  }

  // ------------------------------------------------------------------ log

  const LOG_MAX = 1200;

  function lineClass(line) {
    if (line.startsWith('$ ')) return 'c';
    if (/^ERROR\b/.test(line)) return 'e';
    if (/^WARNING\b/.test(line)) return 'w';
    if (line.startsWith('[app]')) return 'a';
    if (/^\[(download|info|youtube)/.test(line)) return 'm';
    return '';
  }

  function resetLog() {
    el.log.replaceChildren();
    S.logCount = 0;
    el.logCount.textContent = '0';
    el.lastLine.textContent = '';
  }

  function appendLog({ seq, line }) {
    if (seq <= S.logSeq) return;
    S.logSeq = seq;
    const atBottom = el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight < 24;
    const span = document.createElement('span');
    const cls = lineClass(line);
    if (cls) span.className = cls;
    span.textContent = `${line}\n`;
    el.log.append(span);
    while (el.log.childNodes.length > LOG_MAX) el.log.firstChild.remove();
    if (atBottom) el.log.scrollTop = el.log.scrollHeight;
    S.logCount += 1;
    el.logCount.textContent = String(S.logCount);
    el.lastLine.textContent = line;
  }

  function setDrawer(open) {
    el.drawer.toggleAttribute('data-open', open);
    el.drawer.inert = !open;
    el.logToggle.setAttribute('aria-expanded', String(open));
    if (open) {
      el.log.scrollTop = el.log.scrollHeight;
      el.log.focus({ preventScroll: true });
    } else if (el.drawer.contains(document.activeElement)) {
      el.logToggle.focus();
    }
  }

  // ------------------------------------------------------------------ server events

  function onEvent(msg) {
    switch (msg.type) {
      case 'hello':
        S.version = msg.version;
        renderVersion();
        resetLog();
        S.logSeq = 0;
        (msg.log || []).forEach(appendLog);
        if (msg.job) {
          setJob(msg.job, true);
        } else if (S.job || S.update) {
          S.job = null; // the app was restarted: drop results from the previous run
          S.update = null;
          render();
        }
        break;
      case 'job':
        setJob(msg.job);
        break;
      case 'log':
        appendLog(msg);
        break;
      case 'log-reset':
        resetLog();
        break;
      case 'version':
        S.version = msg.version;
        renderVersion();
        break;
      case 'notice':
        addNotice(msg);
        break;
      default:
        break;
    }
  }

  function connect() {
    const source = new EventSource(`/api/events?t=${encodeURIComponent(TOKEN)}`);
    source.onopen = () => el.app.removeAttribute('data-offline');
    source.onmessage = (e) => {
      try { onEvent(JSON.parse(e.data)); } catch (err) { console.error(err); }
    };
    source.onerror = () => { el.app.dataset.offline = ''; };
  }

  // ------------------------------------------------------------------ wiring

  function wire() {
    el.url.addEventListener('input', () => {
      onUrlEdited();
      clearTimeout(wire.previewTimer);
      wire.previewTimer = setTimeout(() => loadPreview(el.url.value), 320);
    });
    el.url.addEventListener('paste', () => {
      setTimeout(() => { clearTimeout(wire.previewTimer); loadPreview(el.url.value); }, 0);
    });
    [el.url, el.fname].forEach((input) => input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        startExtract();
      }
    }));
    el.form.addEventListener('submit', (e) => e.preventDefault());
    el.go.addEventListener('click', onGo);

    el.pasteBtn.addEventListener('click', async () => {
      const url = await readClipboard();
      if (url) {
        setUrl(url);
      } else {
        nudge(el.urlWrap);
        addNotice({ level: 'warn', code: 'clipboard', text: 'The clipboard doesn’t hold a link.' });
      }
    });
    el.clipUse.addEventListener('click', () => { if (S.clipUrl) setUrl(S.clipUrl); });
    el.clipDismiss.addEventListener('click', () => {
      S.clipDismissed = S.clipUrl || '';
      S.clipUrl = null;
      renderClip();
    });

    el.folder.addEventListener('change', () => { el.folder.title = el.folder.value; savePrefs(); });
    el.cookies.addEventListener('change', savePrefs);
    el.browseBtn.addEventListener('click', async () => {
      el.browseBtn.disabled = true;
      try {
        const res = await api('/api/browse', { initial: el.folder.value });
        if (res.path) fillFolders(res.folders, res.path);
      } catch {
        /* dialog closed or failed */
      } finally {
        el.browseBtn.disabled = false;
      }
    });

    el.playBtn.addEventListener('click', () => { if (S.job && S.job.file) openPath(S.job.file, 'play'); });
    el.revealBtn.addEventListener('click', () => { if (S.job && S.job.file) openPath(S.job.file, 'reveal'); });

    el.updateBtn.addEventListener('click', async () => {
      try {
        const { job } = await api('/api/update', {});
        setJob(job);
      } catch (err) {
        addNotice({ level: 'error', code: 'update_failed', text: err.status === 409 ? 'Wait for the current download to finish first.' : 'Couldn’t start the update.' });
      }
    });

    el.logToggle.addEventListener('click', () => setDrawer(!el.drawer.hasAttribute('data-open')));
    el.closeLog.addEventListener('click', () => setDrawer(false));
    el.copyLog.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(el.log.textContent);
        el.copyLog.textContent = 'Copied';
      } catch {
        el.copyLog.textContent = 'Couldn’t copy';
      }
      setTimeout(() => { el.copyLog.textContent = 'Copy'; }, 1400);
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (el.drawer.hasAttribute('data-open')) setDrawer(false);
        else if (S.clipUrl) { S.clipDismissed = S.clipUrl; S.clipUrl = null; renderClip(); }
        return;
      }
      const t = e.target;
      const typing = t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v' && !typing && !el.fields.disabled) {
        el.url.focus();
        el.url.select();
      }
    });
    window.addEventListener('focus', () => setTimeout(checkClipboard, 150));
    motionQuery.addEventListener('change', (e) => { reduced = e.matches; applyMotion(); });
  }

  async function boot() {
    el.form = $('form');
    wire();
    if (!TOKEN) {
      swapText(el.title, 'Open Extractor from its launcher', true);
      swapText(el.sub, 'This page needs the link the app opens for you.', true);
      el.fields.disabled = true;
      el.go.disabled = true;
      return;
    }
    let state;
    try {
      state = await api('/api/state');
    } catch {
      el.app.dataset.offline = '';
      swapText(el.title, 'Can’t reach the app', true);
      swapText(el.sub, 'Close this window and launch Extractor again.', true);
      return;
    }
    buildFormats(state.formats);
    chooseFormat(state.prefs.format, true);
    fillFolders(state.folders, state.prefs.folder);
    fillCookies(state.cookies, state.prefs.cookies);
    renderRecent(state.history || []);
    S.version = state.version;
    renderVersion();
    if (!state.ffmpeg_found) {
      addNotice({ level: 'warn', code: 'ffmpeg', text: 'ffmpeg.exe isn’t next to the app, so converting audio will fail. See the README.' });
    }
    render();
    engine.kick(); // swings the tonearm in from its boot angle
    S.booted = true;
    connect();
    setTimeout(() => el.app.removeAttribute('data-booting'), 1400);
    setTimeout(checkClipboard, 700);
  }

  boot();
})();
