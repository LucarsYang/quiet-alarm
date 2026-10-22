"""安靜警報驗收測試的共用 fixture。

合約來源：brain-2026-09/projects/quiet-alarm/spec.md 的「行為」與「測試介面」兩節。
只用規格列出的 DOM id／data 屬性與 window.__qa hook，不依賴任何實作細節。
"""
import datetime
import math
import os
import pathlib
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import wave

import pytest
from playwright.sync_api import expect, sync_playwright

REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
# QA_APP_DIR：改服務別的目錄（只給驗證測試本身用，平常不設）
APP_DIR = pathlib.Path(os.environ.get("QA_APP_DIR") or REPO_DIR)
EVIDENCE = (APP_DIR / "_evidence") if os.environ.get("QA_APP_DIR") else (REPO_DIR.parent / "evidence")  # 截圖證據放 repo 外
T0 = datetime.datetime(2026, 10, 22, 9, 0, 0, tzinfo=datetime.timezone.utc)

expect.set_options(timeout=3000)


# ---------- 本機 http server（service worker 需要 http，不用 file://） ----------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(APP_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 10
    while True:
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            if time.time() > deadline:
                proc.kill()
                raise RuntimeError("http.server 沒起來")
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(timeout=5)


# ---------- 瀏覽器 ----------

@pytest.fixture(scope="session")
def pw():
    with sync_playwright() as p:
        yield p


def launch_chromium(pw, **kw):
    """python playwright 對應的 chromium 版本沒裝時，退回 ms-playwright 快取裡最新的 headless shell。"""
    try:
        return pw.chromium.launch(**kw)
    except Exception as e:
        if "Executable doesn't exist" not in str(e):
            raise
        cache = pathlib.Path.home() / "Library/Caches/ms-playwright"
        exes = sorted(
            cache.glob("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"),
            key=lambda x: int(x.parts[-3].rsplit("-", 1)[1]),
        )
        if not exes:
            raise
        return pw.chromium.launch(executable_path=str(exes[-1]), **kw)


@pytest.fixture(scope="session")
def chromium(pw):
    b = launch_chromium(pw)
    yield b
    b.close()


@pytest.fixture(scope="session")
def webkit(pw):
    b = pw.webkit.launch()
    yield b
    b.close()


# 測試模式下確認沒碰麥克風／Wake Lock：只記錄呼叫次數，不改行為
SPY_SCRIPT = """
(() => {
  window.__spy = { gum: 0, wake: 0 };
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    const orig = md.getUserMedia.bind(md);
    md.getUserMedia = (c) => { window.__spy.gum++; return orig(c); };
  }
  if (navigator.wakeLock && navigator.wakeLock.request) {
    const wl = navigator.wakeLock;
    const orig = wl.request.bind(wl);
    wl.request = (t) => { window.__spy.wake++; return orig(t); };
  }
})();
"""


class QA:
    """測試模式（?test=1）的操作包裝，測試只講行為。"""

    def __init__(self, ctx, page, base_url):
        self.ctx = ctx
        self.page = page
        self.base_url = base_url

    # --- 開頁 ---
    def open(self):
        resp = self.page.goto(self.base_url + "index.html?test=1")
        assert resp is not None and resp.ok, f"index.html 讀不到：HTTP {resp.status if resp else '無回應'}"
        self.page.wait_for_selector("#app[data-screen]")
        # 停住時鐘：之後只靠 run_for 前進
        self.page.clock.pause_at(T0 + datetime.timedelta(seconds=10))
        self.run(0)

    def reopen(self):
        """關掉分頁、在同一個瀏覽器設定檔重開（localStorage 保留）＝使用者重開網頁。"""
        self.page.close()
        self.page = _new_page(self.ctx, self.errors)
        self.open()

    # --- 時間與音量 ---
    def run(self, ms):
        self.page.clock.run_for(ms)

    def level(self, n):
        self.page.evaluate("n => window.__qa.setLevel(n)", n)

    def played(self):
        return self.page.evaluate("() => Array.from(window.__qa.played)")

    # --- 讀狀態 ---
    def screen(self):
        return self.page.get_attribute("#app", "data-screen")

    def mood(self):
        return self.page.get_attribute("#app", "data-mood")

    def text(self, sel):
        return " ".join(self.page.inner_text(sel).split())

    def dots(self):
        return self.page.locator("#quiet-dots .dot").count()

    def dots_on(self):
        return self.page.locator("#quiet-dots .dot.on").count()

    def threshold(self):
        return int(self.page.input_value("#threshold-input"))

    def checked(self, name):
        return self.page.eval_on_selector(
            f'input[type=radio][name="{name}"]:checked', "e => e.value"
        )

    # --- 操作 ---
    def click(self, sel):
        self.page.click(sel)
        self.run(0)

    def start(self):
        self.click("#btn-start")
        self.run(100)
        expect(self.page.locator("#app")).to_have_attribute("data-screen", "listening")

    def settings(self):
        self.click("#btn-settings")
        expect(self.page.locator("#app")).to_have_attribute("data-screen", "settings")

    def back(self):
        self.click("#btn-back")

    def set_threshold(self, n):
        self.page.fill("#threshold-input", str(n))
        self.run(0)

    def choose(self, name, value):
        self.page.check(f'input[type=radio][name="{name}"][value="{value}"]')
        self.run(0)

    def trigger_alarm(self, loud=90, limit_ms=3000):
        """持續大聲直到進警報；回傳經過的毫秒數（100ms 精度）。"""
        self.level(loud)
        t = 0
        while t < limit_ms:
            self.run(100)
            t += 100
            if self.screen() == "alarm":
                return t
        raise AssertionError(f"{limit_ms}ms 內沒進警報，畫面＝{self.screen()}")

    def shot(self, name):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(EVIDENCE / name))


def _new_page(ctx, errors):
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.clock.install(time=T0)
    return page


def _make_qa(browser, base_url):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script(SPY_SCRIPT)
    errors = []
    page = _new_page(ctx, errors)
    qa = QA(ctx, page, base_url)
    qa.errors = errors
    return qa


@pytest.fixture
def qa(chromium, base_url):
    q = _make_qa(chromium, base_url)
    yield q
    errs = list(q.errors)
    q.ctx.close()
    assert not errs, f"page errors: {errs}"


@pytest.fixture
def qa_webkit(webkit, base_url):
    q = _make_qa(webkit, base_url)
    yield q
    errs = list(q.errors)
    q.ctx.close()
    assert not errs, f"page errors: {errs}"


# ---------- 真實管線（不帶 ?test=1） ----------

def write_wav(path, amplitude, seconds=6, freq=440, rate=48000):
    """16-bit mono PCM；amplitude=0 為數位靜音。"""
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = int(round(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate)))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return path


# 大聲：振幅 0.25 → RMS≈0.177 → ≈-15 dBFS → 音量≈92（> 60，且 < 100 可用門檻 100 擋住觸發）
LOUD_AMP = 0.25


@pytest.fixture(scope="session")
def wav_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("wav")
    write_wav(d / "loud.wav", LOUD_AMP)
    write_wav(d / "silence.wav", 0.0)
    return d


FAKE_MEDIA_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
]


@pytest.fixture(scope="session")
def fake_mic_browser(pw, wav_dir):
    """依 wav 名稱開對應的 Chromium（假麥克風輸入在啟動參數，所以每個 wav 一個瀏覽器）。"""
    cache = {}

    def get(name):
        if name not in cache:
            wav = wav_dir / f"{name}.wav"
            cache[name] = launch_chromium(
                pw, args=FAKE_MEDIA_ARGS + [f"--use-file-for-fake-audio-capture={wav}"]
            )
        return cache[name]

    yield get
    for b in cache.values():
        b.close()


# 真實模式下替換 Wake Lock（headless 拿不到真的），並記錄 getUserMedia 參數與回傳的 stream、AudioContext 建立次數
REAL_SPY_SCRIPT = """
(() => {
  window.__gum = [];
  window.__ac = 0;
  window.__wl = { requested: 0, released: 0 };
  const md = navigator.mediaDevices;
  const origGum = md.getUserMedia.bind(md);
  md.getUserMedia = async (c) => {
    const s = await origGum(c);
    window.__gum.push({ c: JSON.parse(JSON.stringify(c)), s });
    return s;
  };
  const fakeWakeLock = {
    request: async (type) => {
      window.__wl.requested++;
      const s = new EventTarget();
      s.type = type; s.released = false; s.onrelease = null;
      s.release = async () => {
        if (s.released) return;
        s.released = true; window.__wl.released++;
        const ev = new Event('release');
        s.dispatchEvent(ev);
        if (typeof s.onrelease === 'function') s.onrelease(ev);
      };
      return s;
    },
  };
  Object.defineProperty(navigator, 'wakeLock', { configurable: true, get: () => fakeWakeLock });
  const AC = window.AudioContext;
  window.AudioContext = class extends AC { constructor(...a) { super(...a); window.__ac++; } };
})();
"""


@pytest.fixture
def real_page(fake_mic_browser, base_url):
    """回傳 open(wav_name, extra_init=None) → page；不裝 page.clock，用真實時間。"""
    ctxs = []
    errors = []

    def open_(wav_name, extra_init=None):
        ctx = fake_mic_browser(wav_name).new_context(
            viewport={"width": 390, "height": 844}, permissions=["microphone"]
        )
        ctxs.append(ctx)
        ctx.add_init_script(REAL_SPY_SCRIPT)
        if extra_init:
            ctx.add_init_script(extra_init)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        resp = page.goto(base_url + "index.html")
        assert resp is not None and resp.ok, f"index.html 讀不到：HTTP {resp.status if resp else '無回應'}"
        page.wait_for_selector("#app[data-screen]")
        return page

    yield open_
    for c in ctxs:
        c.close()
    assert not errors, f"page errors: {errors}"


def level_value(page):
    return int(page.inner_text("#level-value").strip())
