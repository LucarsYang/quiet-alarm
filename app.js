/* 安靜警報：DOM、麥克風、聲音、Wake Lock。狀態與規則在 logic.js。 */
(function () {
  'use strict';
  var L = window.QuietLogic;
  var TEST = new URLSearchParams(location.search).get('test') === '1';
  var TEST_PLAY_MS = 2000;   // 測試模式：每次播放視為 2 秒
  var BEEP_MS = 1500;
  var RECORD_MS = 3000;
  var MIC_CONSTRAINTS = { audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } };
  var TEXT_DENIED = '沒有麥克風權限，請到瀏覽器設定允許';
  var TEXT_LOST = '麥克風斷了，請再按一次開始';
  var TEXT_FLOAT_FAIL = '開不了浮動小視窗';
  var PIP_OK = 'documentPictureInPicture' in window;   // Chrome／Edge 116+、Firefox 151+；Safari 與手機沒有
  var MOODS = {
    calm: { face: '😊', text: '很安靜' },
    warn: { face: '😐', text: '有點吵' },
    loud: { face: '😣', text: '太吵了' },
  };

  function $(id) { return document.getElementById(id); }
  var el = {
    app: $('app'), level: $('level-value'), fill: $('level-fill'), mark: $('threshold-mark'),
    thLabel: $('threshold-label'), thNow: $('threshold-now'), moodText: $('mood-text'), moodFace: $('mood-face'),
    dots: $('quiet-dots'), alarmSub: $('alarm-sub'), error: $('error-text'), live: $('live-bar'),
    thInput: $('threshold-input'), useCurrent: $('btn-use-current'), recordRow: $('record-row'),
    record: $('btn-record'), preview: $('btn-preview'), recordHint: $('record-hint'),
    float: $('btn-float'), floatError: $('float-error'),
  };

  // ---------- 設定 ----------
  function loadSettings() {
    try { return L.parseSettings(localStorage.getItem(L.SETTINGS_KEY)); } catch (e) { return L.sanitizeSettings(null); }
  }
  var settings = loadSettings();
  function saveSettings() {
    try { localStorage.setItem(L.SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* 私密模式等存不了就算了 */ }
  }

  var m = L.createMachine(function () { return settings; });

  // ---------- 狀態（瀏覽器端） ----------
  var smoothed = 0;          // EMA 後的音量（0～100，未取整）
  var tickTimer = null;
  var tickHost = window;     // 計時器掛在哪個 window（小視窗開著就掛小視窗，避開背景分頁節流）
  var playTimer = null;      // 測試模式的假播放計時
  var starting = false;
  var ctx = null, analyser = null, sink = null, source = null, stream = null, buf = null;
  var micLive = false;       // 麥克風正在送資料（播放期間會暫停）
  var micPending = null;     // 重新取得麥克風的 promise（去重）
  var wakeLock = null;
  var voiceBuffer = null, voiceLoading = null;
  var customBlob = null, customBuffer = null;
  var currentSound = null;   // 正在播的 AudioBufferSourceNode／OscillatorNode 等
  var recording = false;
  var pipWin = null;         // 浮動小視窗（Document Picture-in-Picture）的 window
  var pipEl = null;          // 小視窗裡的元素
  var pipOpening = false;
  var floatFailed = false;   // 開窗失敗紅字（監聽畫面也看得到）
  var qa = null;

  if (TEST) {
    qa = window.__qa = {
      played: [],
      setLevel: function (n) { smoothed = L.clamp(Number(n) || 0, 0, 100); },
    };
  }

  function now() { return performance.now(); }
  function levelInt() { return Math.round(smoothed); }

  // ---------- 畫面 ----------
  function render() {
    var lv = levelInt();
    var th = settings.threshold;
    var mood = L.moodOf(lv, th);
    el.app.dataset.screen = m.screen;
    el.app.dataset.mood = mood;
    document.body.classList.toggle('alarm', m.screen === 'alarm');

    el.level.textContent = String(lv);
    el.fill.style.width = lv + '%';
    el.mark.style.left = th + '%';
    el.thLabel.textContent = '警報 ' + th;
    el.thNow.textContent = String(th);
    el.moodText.textContent = MOODS[mood].text;
    el.moodFace.textContent = MOODS[mood].face;
    el.live.style.width = (m.running ? lv : 0) + '%';
    if (String(el.thInput.value) !== String(th)) el.thInput.value = th;
    el.useCurrent.disabled = !m.running;

    // 警報圓點
    var want = settings.quiet;
    if (el.dots.children.length !== want) {
      el.dots.textContent = '';
      for (var i = 0; i < want; i++) {
        var d = document.createElement('div');
        d.className = 'dot';
        el.dots.appendChild(d);
      }
    }
    for (var j = 0; j < el.dots.children.length; j++) el.dots.children[j].classList.toggle('on', j < m.dotsOn);
    el.alarmSub.textContent = '安靜 ' + settings.quiet + ' 秒就會停';

    // 浮動小視窗
    el.float.hidden = !PIP_OK || !!pipWin || pipOpening;
    el.floatError.textContent = floatFailed ? TEXT_FLOAT_FAIL : '';
    renderPip(lv, th, mood);

    // 錄音
    var custom = settings.sound === 'custom';
    el.recordRow.hidden = !custom;
    var has = hasCustom();
    el.preview.hidden = !has || recording;
    el.record.disabled = recording;
    if (!recording) {
      el.record.textContent = has ? '🎙️ 重錄 3 秒' : '🎙️ 錄音 3 秒';
      el.recordHint.textContent = has ? '已錄好' : '還沒錄，響的時候會用嗶嗶聲';
    }
  }

  function syncSettingsForm() {
    el.thInput.value = settings.threshold;
    ['sustain', 'sound', 'quiet'].forEach(function (name) {
      var v = String(settings[name]);
      var inputs = document.querySelectorAll('input[name="' + name + '"]');
      for (var i = 0; i < inputs.length; i++) inputs[i].checked = inputs[i].value === v;
    });
  }

  function showError(text) { el.error.textContent = text || ''; }
  function clearFloatError() {
    if (!floatFailed) return;
    floatFailed = false;
    if (el.error.textContent === TEXT_FLOAT_FAIL) showError('');
  }

  // ---------- 浮動小視窗（電腦版） ----------
  var PIP_CSS = [
    ':root{--ink:#2b2b2b;--muted:#7a776f;--green:#3fb27f;--yellow:#f2b632;--red:#e5484d}',
    '*{box-sizing:border-box}',
    'html,body{margin:0;height:100%}',
    'body{background:#fff;color:var(--ink);font-family:-apple-system,"PingFang TC","Noto Sans TC",sans-serif;-webkit-user-select:none;user-select:none;overflow:hidden}',
    '#pip-root{height:100%;display:flex}',
    '.pv{display:none;flex:1;min-width:0}',
    '#pip-root[data-screen="listening"] .pv-listening{display:flex;align-items:center;gap:12px;padding:12px 14px}',
    '#pip-root[data-screen="alarm"] .pv-alarm{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;padding:12px 14px}',
    '#pip-root[data-screen="stopped"] .pv-stopped{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;padding:12px 14px;text-align:center}',
    '#pip-root[data-screen="alarm"]{background:var(--red);color:#fff;animation:flash .8s steps(1) infinite}',
    '@keyframes flash{50%{background:#b8262b}}',
    '.face{width:52px;height:52px;border-radius:50%;display:grid;place-items:center;font-size:30px;flex:none}',
    '#pip-root[data-mood="calm"] .face{background:#e3f5ec}',
    '#pip-root[data-mood="warn"] .face{background:#fdf1d6}',
    '#pip-root[data-mood="loud"] .face{background:#fbe1e2}',
    '.info{flex:1;min-width:0}',
    '.st{font-size:15px;font-weight:700;margin-bottom:8px}',
    '#pip-root[data-mood="calm"] .st{color:var(--green)}',
    '#pip-root[data-mood="warn"] .st{color:#d99a0b}',
    '#pip-root[data-mood="loud"] .st{color:var(--red)}',
    '.bar{position:relative;height:12px;border-radius:6px;background:#eeebe4}',
    '.fill{height:100%;width:0;border-radius:6px;transition:width .1s linear}',
    '#pip-root[data-mood="calm"] .fill{background:var(--green)}',
    '#pip-root[data-mood="warn"] .fill{background:var(--yellow)}',
    '#pip-root[data-mood="loud"] .fill{background:var(--red)}',
    '.thr{position:absolute;top:-4px;bottom:-4px;width:2px;margin-left:-1px;background:var(--ink);border-radius:1px;left:65%}',
    '.nums{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:5px}',
    '.nums b{color:var(--ink);font-variant-numeric:tabular-nums}',
    '.title{font-size:24px;font-weight:800;letter-spacing:2px}',
    '.dots{display:flex;gap:7px}',
    '.dot{width:14px;height:14px;border-radius:50%;border:2px solid #fff}',
    '.dot.on{background:#fff}',
    '.dismiss{display:block;width:100%;border:0;border-radius:10px;padding:6px 0;background:#fff;color:var(--red);font:inherit;font-size:14px;font-weight:700;cursor:pointer}',
    '.stop-title{font-size:18px;font-weight:800}',
    '.stop-hint{font-size:12px;color:var(--muted)}',
  ].join('\n');

  var PIP_HTML =
    '<div id="pip-root" data-screen="listening" data-mood="calm">' +
      '<div class="pv pv-listening">' +
        '<div class="face" id="pip-face">😊</div>' +
        '<div class="info">' +
          '<div class="st" id="pip-mood-text">很安靜</div>' +
          '<div class="bar"><div class="fill" id="pip-fill"></div><div class="thr" id="pip-thr"></div></div>' +
          '<div class="nums"><span>現在 <b id="pip-level">0</b></span><span id="pip-threshold">警報 65</span></div>' +
        '</div>' +
      '</div>' +
      '<div class="pv pv-alarm">' +
        '<div class="title">請安靜！</div>' +
        '<div class="dots" id="pip-dots"></div>' +
        '<button type="button" class="dismiss" id="pip-dismiss">解除</button>' +
      '</div>' +
      '<div class="pv pv-stopped">' +
        '<div class="stop-title">已停止</div>' +
        '<div class="stop-hint">回主頁按開始</div>' +
      '</div>' +
    '</div>';

  function pipScreen() {
    if (m.screen === 'alarm') return 'alarm';
    if (m.running && (m.screen === 'listening' || m.screen === 'settings')) return 'listening';
    return 'stopped';
  }

  function renderPip(lv, th, mood) {
    if (!pipEl) return;
    var p = pipEl;
    p.root.setAttribute('data-screen', pipScreen());
    p.root.setAttribute('data-mood', mood);
    p.face.textContent = MOODS[mood].face;
    p.moodText.textContent = MOODS[mood].text;
    p.level.textContent = String(lv);
    p.fill.style.width = lv + '%';
    p.thr.style.left = th + '%';
    p.threshold.textContent = '警報 ' + th;
    var want = settings.quiet;
    if (p.dots.children.length !== want) {
      p.dots.textContent = '';
      for (var i = 0; i < want; i++) {
        var d = p.doc.createElement('span');
        d.className = 'dot';
        p.dots.appendChild(d);
      }
    }
    for (var j = 0; j < p.dots.children.length; j++) p.dots.children[j].classList.toggle('on', j < m.dotsOn);
  }

  function buildPip(w) {
    var d = w.document;
    try { d.title = '安靜警報'; } catch (e) {}
    var style = d.createElement('style');
    style.textContent = PIP_CSS;
    (d.head || d.documentElement).appendChild(style);
    d.body.innerHTML = PIP_HTML;
    function g(id) { return d.getElementById(id); }
    pipEl = {
      doc: d, root: g('pip-root'), face: g('pip-face'), moodText: g('pip-mood-text'), level: g('pip-level'),
      fill: g('pip-fill'), thr: g('pip-thr'), threshold: g('pip-threshold'), dots: g('pip-dots'),
    };
    g('pip-dismiss').addEventListener('click', dismiss);
  }

  function onPipHide() {
    var w = pipWin;
    if (!w) return;
    var moveTicker = tickTimer && tickHost === w;
    if (moveTicker) stopTicker();   // 小視窗還沒關乾淨前清掉它身上的計時器
    pipWin = null;
    pipEl = null;
    if (moveTicker && m.running) startTicker();   // 搬回主頁
    render();
  }

  function openFloat() {
    if (!PIP_OK || pipWin || pipOpening) return;
    var fail = function () {
      pipOpening = false;
      floatFailed = true;
      showError(TEXT_FLOAT_FAIL);
      render();
    };
    var req;
    try {
      req = window.documentPictureInPicture.requestWindow({ width: 240, height: 140 });
    } catch (e) { fail(); return; }
    pipOpening = true;
    render();
    Promise.resolve(req).then(function (w) {
      pipOpening = false;
      try {
        if (!w || !w.document || !w.document.body) throw new Error('no window');
        pipWin = w;
        buildPip(w);
        w.addEventListener('pagehide', onPipHide);
      } catch (e) {
        pipWin = null;
        pipEl = null;
        try { if (w && w.close) w.close(); } catch (e2) {}
        fail();
        return;
      }
      clearFloatError();
      if (m.running) startTicker();   // 計時器改掛到小視窗
      render();
    }, fail);
  }

  // ---------- 計時 ----------
  // 小視窗開著就把量測計時器掛在小視窗的 window：主頁分頁在背景時 Chrome 會把主頁的 setInterval
  // 壓到 1 秒以上，但小視窗本身一直是可見的，掛在它身上的計時器不受背景節流影響。
  function startTicker() {
    stopTicker();
    tickHost = pipWin || window;
    tickTimer = tickHost.setInterval(tick, L.TICK_MS);
  }
  function stopTicker() {
    if (tickTimer) { try { tickHost.clearInterval(tickTimer); } catch (e) {} }
    tickTimer = null;
    tickHost = window;
  }

  function readMicLevel() {
    if (!analyser) return;
    if (!buf || buf.length !== analyser.fftSize) buf = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buf);
    var raw = L.levelFromDbfs(L.dbfsFromRms(L.rmsOf(buf)));
    smoothed = L.ema(smoothed, raw);
  }

  function tick() {
    if (!m.running) return;
    if (!TEST) {
      // 播放中或重新取得麥克風中：不偵測
      if (!micLive) { m.lastT = now(); render(); return; }
      readMicLevel();
    }
    var events = m.tick(levelInt(), now());
    events.forEach(function (ev) { if (ev.type === 'alarm') playAlarm(ev.id); });
    render();
  }

  // ---------- 麥克風與 AudioContext ----------
  function ensureAudioContext() {
    if (TEST) return null;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx || ctx.state === 'closed') {
      ctx = new AC();
      analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0;
      // 部分瀏覽器（舊 Safari）analyser 沒接到輸出就不跑；接一個 0 增益到喇叭
      sink = ctx.createGain();
      sink.gain.value = 0;
      analyser.connect(sink);
      sink.connect(ctx.destination);
    }
    if (ctx.state !== 'running') ctx.resume().catch(function () {});
    return ctx;
  }

  // iPhone 在使用者點擊時播一段無聲，解鎖之後的出聲
  function unlockAudio() {
    if (!ctx) return;
    try {
      var b = ctx.createBuffer(1, 1, ctx.sampleRate);
      var s = ctx.createBufferSource();
      s.buffer = b;
      s.connect(ctx.destination);
      s.start(0);
    } catch (e) { /* 忽略 */ }
  }

  function setAudioSession(type) {
    try { if (navigator.audioSession) navigator.audioSession.type = type; } catch (e) { /* 不支援 */ }
  }

  function stopTracks(s) {
    if (!s) return;
    s.getTracks().forEach(function (t) { t.onended = null; try { t.stop(); } catch (e) {} });
  }

  function attachStream(s) {
    stream = s;
    if (source) { try { source.disconnect(); } catch (e) {} }
    source = ctx.createMediaStreamSource(s);
    source.connect(analyser);
    s.getAudioTracks().forEach(function (t) {
      t.onended = function () { if (stream === s && m.running) lost(TEXT_LOST); };
    });
    micLive = true;
  }

  // 暫停麥克風（播放警報聲前）：停掉 track，避免 iPhone 錄音模式下聲音變小、從聽筒出聲
  function pauseMic() {
    micLive = false;
    if (source) { try { source.disconnect(); } catch (e) {} source = null; }
    var s = stream;
    stream = null;
    stopTracks(s);
  }

  // 重新取得麥克風；成功回 true。失敗：回開始畫面＋紅字
  function resumeMic() {
    if (TEST) return Promise.resolve(true);
    if (micLive && stream) return Promise.resolve(true);
    if (micPending) return micPending;
    setAudioSession('auto');
    micPending = navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS).then(function (s) {
      micPending = null;
      if (!m.running) { stopTracks(s); return false; }
      ensureAudioContext();
      attachStream(s);
      return true;
    }, function (e) {
      micPending = null;
      if (m.running) lost(e && e.name === 'NotAllowedError' ? TEXT_DENIED : TEXT_LOST);
      return false;
    });
    return micPending;
  }

  // ---------- Wake Lock ----------
  function requestWakeLock() {
    if (TEST || !('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
    if (wakeLock && !wakeLock.released) return;
    navigator.wakeLock.request('screen').then(function (lock) {
      if (!m.running && !starting) { lock.release().catch(function () {}); return; }
      wakeLock = lock;
      lock.addEventListener('release', function () { if (wakeLock === lock) wakeLock = null; });
    }).catch(function () { /* 不支援或被拒：不影響使用 */ });
  }
  function releaseWakeLock() {
    var lock = wakeLock;
    wakeLock = null;
    if (lock) lock.release().catch(function () {});
  }

  // ---------- 開始／停止 ----------
  function start() {
    if (m.running || starting) return;
    floatFailed = false;
    showError('');
    if (TEST) {
      smoothed = 0;
      m.start(now());
      startTicker();
      render();
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError(TEXT_DENIED);
      return;
    }
    starting = true;
    // 以下兩個在點擊當下同步做（iPhone 要使用者手勢才能出聲）
    ensureAudioContext();
    unlockAudio();
    setAudioSession('auto');
    navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS).then(function (s) {
      starting = false;
      ensureAudioContext();
      smoothed = 0;
      attachStream(s);
      requestWakeLock();
      loadVoice();
      m.start(now());
      startTicker();
      render();
    }, function (e) {
      starting = false;
      showError(e && (e.name === 'NotFoundError' || e.name === 'OverconstrainedError') ? '找不到麥克風' : TEXT_DENIED);
      render();
    });
  }

  function teardown() {
    stopTicker();
    stopSound();
    if (playTimer) { clearTimeout(playTimer); playTimer = null; }
    pauseMic();
    releaseWakeLock();
    smoothed = 0;
  }

  function stop() {
    m.stop();
    teardown();
    clearFloatError();
    render();
  }

  // 麥克風斷了／重新取得失敗：回開始畫面＋紅字
  function lost(text) {
    m.stop();
    teardown();
    showError(text);
    render();
  }

  // ---------- 聲音 ----------
  function hasCustom() { return !!customBlob; }

  function loadVoice() {
    if (TEST || voiceBuffer || voiceLoading || !ctx) return voiceLoading;
    voiceLoading = fetch('sounds/please-quiet.m4a')
      .then(function (r) { if (!r.ok) throw new Error('voice ' + r.status); return r.arrayBuffer(); })
      .then(decode)
      .then(function (b) { voiceBuffer = b; return b; })
      .catch(function () { voiceLoading = null; return null; });
    return voiceLoading;
  }

  function decode(arr) {
    return new Promise(function (resolve, reject) {
      try {
        var p = ctx.decodeAudioData(arr, resolve, reject);
        if (p && p.then) p.then(resolve, reject);
      } catch (e) { reject(e); }
    });
  }

  function loadCustomBuffer() {
    if (customBuffer) return Promise.resolve(customBuffer);
    if (!customBlob || !ctx) return Promise.resolve(null);
    return customBlob.arrayBuffer().then(decode).then(function (b) { customBuffer = b; return b; })
      .catch(function () { return null; });
  }

  function stopSound() {
    var s = currentSound;
    currentSound = null;
    if (!s) return;
    if (s.finish) s.finish();
    (s.nodes || []).forEach(function (n) { try { n.stop(); } catch (e) {} try { n.disconnect(); } catch (e) {} });
  }

  // 播 AudioBuffer，播完 resolve
  function playBuffer(b) {
    return new Promise(function (resolve) {
      var src = ctx.createBufferSource();
      src.buffer = b;
      src.connect(ctx.destination);
      var done = false;
      var finish = function () { if (done) return; done = true; clearTimeout(guard); resolve(); };
      var guard = setTimeout(finish, b.duration * 1000 + 500);
      src.onended = finish;
      currentSound = { nodes: [src], finish: finish };
      src.start();
    });
  }

  // 880Hz 三聲，共約 1.5 秒
  function playBeep() {
    return new Promise(function (resolve) {
      var t0 = ctx.currentTime + 0.02;
      var g = ctx.createGain();
      g.gain.value = 0;
      g.connect(ctx.destination);
      var osc = ctx.createOscillator();
      osc.type = 'square';
      osc.frequency.value = 880;
      osc.connect(g);
      for (var i = 0; i < 3; i++) {
        var a = t0 + i * 0.5;
        g.gain.setValueAtTime(0, a);
        g.gain.linearRampToValueAtTime(0.35, a + 0.01);
        g.gain.setValueAtTime(0.35, a + 0.33);
        g.gain.linearRampToValueAtTime(0, a + 0.35);
      }
      osc.start(t0);
      osc.stop(t0 + 1.5);
      var done = false;
      var finish = function () { if (done) return; done = true; clearTimeout(guard); resolve(); };
      var guard = setTimeout(finish, BEEP_MS + 300);
      osc.onended = finish;
      currentSound = { nodes: [osc, g], finish: finish };
    });
  }

  // 播一種聲音（voice／beep／custom），播完 resolve；載不到就改 beep
  function playKind(kind) {
    if (!ctx) return Promise.resolve();
    if (ctx.state !== 'running') ctx.resume().catch(function () {});
    var load = kind === 'voice' ? (voiceBuffer ? Promise.resolve(voiceBuffer) : (loadVoice() || Promise.resolve(null)))
      : kind === 'custom' ? loadCustomBuffer() : Promise.resolve(null);
    return load.then(function (b) { return b ? playBuffer(b) : playBeep(); });
  }

  function playAlarm(id) {
    var kind = L.resolveSound(settings.sound, hasCustom());
    if (!kind) { m.playbackEnded(id); return; }
    if (TEST) {
      qa.played.push(kind);
      if (playTimer) clearTimeout(playTimer);
      playTimer = setTimeout(function () { playTimer = null; m.playbackEnded(id); render(); }, TEST_PLAY_MS);
      return;
    }
    // 播放期間停掉麥克風，播完重新取得才開始數安靜秒數
    pauseMic();
    setAudioSession('playback');
    playKind(kind).catch(function () {}).then(function () {
      if (!m.running || m.alarmId !== id) return;
      currentSound = null;
      return resumeMic().then(function (ok) {
        if (ok) { m.playbackEnded(id); render(); }
      });
    });
  }

  function dismiss() {
    if (m.screen !== 'alarm') return;
    m.dismiss();
    if (playTimer) { clearTimeout(playTimer); playTimer = null; }
    if (!TEST) { stopSound(); resumeMic(); }
    render();
  }

  // ---------- 自己錄（IndexedDB） ----------
  var DB_NAME = 'quiet-alarm', STORE = 'sounds', KEY = 'custom';
  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error('no idb')); return; }
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () { req.result.createObjectStore(STORE); };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }
  function idb(mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, mode);
        var req = fn(tx.objectStore(STORE));
        tx.oncomplete = function () { db.close(); resolve(req && req.result); };
        tx.onerror = tx.onabort = function () { db.close(); reject(tx.error); };
      });
    });
  }
  function loadCustom() {
    return idb('readonly', function (st) { return st.get(KEY); }).then(function (rec) {
      if (rec && rec.blob) { customBlob = rec.blob; customBuffer = null; render(); }
    }).catch(function () {});
  }
  function saveCustom(blob) {
    customBlob = blob;
    customBuffer = null;
    return idb('readwrite', function (st) { return st.put({ blob: blob, type: blob.type, at: Date.now() }, KEY); })
      .catch(function () { /* 存不了：這次開著還能用 */ });
  }

  function record() {
    if (recording) return;
    if (TEST) {
      // 測試模式不開麥克風：直接當作錄好了
      customBlob = new Blob([], { type: 'audio/webm' });
      render();
      return;
    }
    if (!window.MediaRecorder || !navigator.mediaDevices) {
      el.recordHint.textContent = '這個瀏覽器不能錄音';
      return;
    }
    ensureAudioContext();
    unlockAudio();
    recording = true;
    el.record.textContent = '錄音中…';
    el.recordHint.textContent = '請對著手機說話（3 秒）';
    render();
    // 監聽中就用同一個麥克風（iPhone 再開一個會讓原本的斷掉）；沒開始就另外開
    var reuse = m.running && micLive && stream;
    var get = reuse ? Promise.resolve(stream) : navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
    get.then(function (s) {
      var chunks = [];
      var rec = new MediaRecorder(s);
      rec.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = function () {
        if (!reuse) stopTracks(s);
        recording = false;
        if (chunks.length) saveCustom(new Blob(chunks, { type: rec.mimeType || chunks[0].type })).then(render);
        render();
      };
      rec.start();
      setTimeout(function () { try { rec.stop(); } catch (e) { recording = false; render(); } }, RECORD_MS);
    }).catch(function (e) {
      recording = false;
      render();
      el.recordHint.textContent = e && e.name === 'NotAllowedError' ? TEXT_DENIED : '錄音失敗，請再試一次';
    });
  }

  function preview() {
    if (TEST || !customBlob) return;
    ensureAudioContext();
    stopSound();
    loadCustomBuffer().then(function (b) {
      if (b) playBuffer(b);
      else el.recordHint.textContent = '這段錄音播不出來，請重錄';
    });
  }

  // ---------- iPhone：螢幕關掉再回來 ----------
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible' || !m.running) return;
    requestWakeLock();
    if (ctx && ctx.state !== 'running') ctx.resume().catch(function () {});
    // 正在播放／重新取得中的暫停不算斷線
    if (micLive && stream) {
      var dead = stream.getAudioTracks().some(function (t) { return t.readyState === 'ended'; });
      if (dead) lost(TEXT_LOST);
    }
  });

  // ---------- 事件 ----------
  $('btn-start').addEventListener('click', start);
  $('btn-stop').addEventListener('click', stop);
  el.float.addEventListener('click', openFloat);
  $('btn-settings').addEventListener('click', function () { m.openSettings(); render(); });
  $('btn-back').addEventListener('click', function () { m.back(); render(); });
  $('btn-dismiss').addEventListener('click', dismiss);
  el.record.addEventListener('click', record);
  el.preview.addEventListener('click', preview);
  el.useCurrent.addEventListener('click', function () {
    var th = m.useCurrent(now());
    if (th == null) return;
    settings.threshold = th;
    saveSettings();
    render();
  });
  el.thInput.addEventListener('input', function () {
    settings.threshold = L.sanitizeSettings({ threshold: el.thInput.value }).threshold;
    saveSettings();
    render();
  });
  ['sustain', 'sound', 'quiet'].forEach(function (name) {
    var inputs = document.querySelectorAll('input[name="' + name + '"]');
    for (var i = 0; i < inputs.length; i++) {
      inputs[i].addEventListener('change', function (e) {
        if (!e.target.checked) return;
        var patch = Object.assign({}, settings);
        patch[name] = e.target.value;
        settings = L.sanitizeSettings(patch);
        saveSettings();
        render();
      });
    }
  });

  // ---------- 啟動 ----------
  syncSettingsForm();
  render();
  loadCustom();
  if (!TEST && 'serviceWorker' in navigator && location.protocol !== 'file:') {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () {});
    });
  }
})();
