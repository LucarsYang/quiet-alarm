/* 安靜警報：純函式與狀態機（不碰 DOM、麥克風、聲音）。
 * 瀏覽器：window.QuietLogic；Node：module.exports。 */
(function (root) {
  'use strict';

  var SETTINGS_KEY = 'quiet-alarm-settings';
  var DEFAULTS = { threshold: 65, sustain: 1, sound: 'voice', quiet: 3 };
  var SUSTAIN_OPTIONS = [0.5, 1, 2];
  var SOUND_OPTIONS = ['voice', 'beep', 'custom', 'none'];
  var QUIET_OPTIONS = [2, 3, 5];
  var TICK_MS = 100;
  var EMA_ALPHA = 0.3;
  var HISTORY_MS = 2000;   // 「用現在的音量設定」看最近幾毫秒
  var MAX_DT = 250;        // 計時器被延遲（背景、卡頓）時，一次最多算這麼多毫秒

  function clamp(x, lo, hi) { return Math.min(hi, Math.max(lo, x)); }

  // ---------- 設定 ----------
  function sanitizeSettings(raw) {
    var s = Object.assign({}, DEFAULTS);
    if (!raw || typeof raw !== 'object') return s;
    var th = Number(raw.threshold);
    if (isFinite(th)) s.threshold = Math.round(clamp(th, 0, 100));
    var su = Number(raw.sustain);
    if (SUSTAIN_OPTIONS.indexOf(su) >= 0) s.sustain = su;
    if (SOUND_OPTIONS.indexOf(raw.sound) >= 0) s.sound = raw.sound;
    var q = Number(raw.quiet);
    if (QUIET_OPTIONS.indexOf(q) >= 0) s.quiet = q;
    return s;
  }

  function parseSettings(json) {
    try { return sanitizeSettings(JSON.parse(json)); } catch (e) { return sanitizeSettings(null); }
  }

  // ---------- 音量 ----------
  function rmsOf(samples) {
    if (!samples || !samples.length) return 0;
    var sum = 0;
    for (var i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    return Math.sqrt(sum / samples.length);
  }

  function dbfsFromRms(rms) {
    return rms > 0 ? 20 * Math.log10(rms) : -Infinity;
  }

  // -70 dBFS＝0、-10 dBFS＝100，線性、夾在 0～100（不取整，取整在顯示）
  function levelFromDbfs(db) {
    if (!isFinite(db)) return 0;
    return clamp((db + 70) * 100 / 60, 0, 100);
  }

  function ema(prev, x, alpha) {
    var a = alpha == null ? EMA_ALPHA : alpha;
    return a * x + (1 - a) * prev;
  }

  function moodOf(level, threshold) {
    if (level >= threshold) return 'loud';
    if (level < threshold * 0.8) return 'calm';
    return 'warn';
  }

  // 最近 2 秒平均＋15，上限 95；沒資料回 null
  function thresholdFromHistory(history, now) {
    var sum = 0, n = 0;
    for (var i = 0; i < history.length; i++) {
      if (history[i].t > now - HISTORY_MS) { sum += history[i].level; n++; }
    }
    if (!n) return null;
    return Math.round(clamp(sum / n + 15, 0, 95));
  }

  // 警報實際要播的聲音；custom 沒錄過改 beep；none 回 null
  function resolveSound(sound, hasCustom) {
    if (sound === 'none') return null;
    if (sound === 'custom') return hasCustom ? 'custom' : 'beep';
    if (sound === 'beep') return 'beep';
    return 'voice';
  }

  // ---------- 狀態機 ----------
  // screen：start｜listening｜alarm｜settings
  // tick(level, now) 回傳事件陣列：{type:'alarm', id}｜{type:'released'}
  function createMachine(getSettings) {
    var m = {
      screen: 'start',
      settingsFrom: 'start',
      running: false,
      level: 0,
      loudMs: 0,
      playing: false,
      quietMs: 0,
      dotsOn: 0,
      alarmId: 0,
      history: [],
      lastT: null,
    };

    function resetListen() { m.loudMs = 0; }

    m.start = function (now) {
      m.running = true;
      m.screen = 'listening';
      m.history = [];
      m.lastT = now;
      resetListen();
    };

    m.stop = function () {
      m.running = false;
      m.screen = 'start';
      m.playing = false;
      m.quietMs = 0;
      m.dotsOn = 0;
      m.history = [];
      m.lastT = null;
      m.alarmId++;
      resetListen();
    };

    m.openSettings = function () {
      if (m.screen !== 'start' && m.screen !== 'listening') return;
      m.settingsFrom = m.screen;
      m.screen = 'settings';
      resetListen();
    };

    m.back = function () {
      if (m.screen !== 'settings') return;
      m.screen = m.running ? 'listening' : 'start';
      resetListen();
    };

    function enterAlarm() {
      m.screen = 'alarm';
      m.playing = true;
      m.quietMs = 0;
      m.dotsOn = 0;
      m.alarmId++;
      return { type: 'alarm', id: m.alarmId };
    }

    function backToListening() {
      m.screen = 'listening';
      m.playing = false;
      m.quietMs = 0;
      m.dotsOn = 0;
      m.alarmId++;
      resetListen();
    }

    m.dismiss = function () {
      if (m.screen !== 'alarm') return;
      backToListening();
    };

    m.playbackEnded = function (id) {
      if (m.screen === 'alarm' && id === m.alarmId) m.playing = false;
    };

    m.useCurrent = function (now) {
      if (!m.running) return null;
      return thresholdFromHistory(m.history, now);
    };

    m.tick = function (level, now) {
      var events = [];
      if (!m.running) return events;
      var dt = m.lastT == null ? TICK_MS : clamp(now - m.lastT, 0, MAX_DT);
      m.lastT = now;
      m.level = level;
      m.history.push({ t: now, level: level });
      while (m.history.length && m.history[0].t <= now - HISTORY_MS - 500) m.history.shift();

      var st = getSettings();
      var th = st.threshold;
      if (m.screen === 'listening') {
        if (level >= th) m.loudMs += dt; else m.loudMs = 0;
        if (m.loudMs >= st.sustain * 1000 - 1e-6) events.push(enterAlarm());
      } else if (m.screen === 'settings') {
        m.loudMs = 0;
      } else if (m.screen === 'alarm' && !m.playing) {
        if (level < th) m.quietMs += dt; else m.quietMs = 0;
        m.dotsOn = Math.min(st.quiet, Math.floor((m.quietMs + 1e-6) / 1000));
        if (m.dotsOn >= st.quiet) {
          backToListening();
          events.push({ type: 'released' });
        }
      }
      return events;
    };

    return m;
  }

  var api = {
    SETTINGS_KEY: SETTINGS_KEY,
    DEFAULTS: DEFAULTS,
    TICK_MS: TICK_MS,
    EMA_ALPHA: EMA_ALPHA,
    clamp: clamp,
    sanitizeSettings: sanitizeSettings,
    parseSettings: parseSettings,
    rmsOf: rmsOf,
    dbfsFromRms: dbfsFromRms,
    levelFromDbfs: levelFromDbfs,
    ema: ema,
    moodOf: moodOf,
    thresholdFromHistory: thresholdFromHistory,
    resolveSound: resolveSound,
    createMachine: createMachine,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.QuietLogic = api;
})(typeof window !== 'undefined' ? window : this);
