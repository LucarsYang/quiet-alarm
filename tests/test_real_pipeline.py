"""真實管線（不帶 ?test=1，真實時間）：Chromium 假麥克風。

- 假麥克風輸入用 --use-file-for-fake-audio-capture=<wav>（conftest 產生大聲正弦波與數位靜音 wav）。
- Wake Lock 在 headless 拿不到，conftest 換成記錄用的假物件；getUserMedia／AudioContext 只包一層記錄，行為不變。
- 音量相關測試先把門檻拉到 100，避免進警報（播放期間不偵測、會停麥克風 track）干擾讀數。
"""
import math

import pytest

from conftest import level_value

DENIED_TEXT = "沒有麥克風權限，請到瀏覽器設定允許"


def _wait_screen(page, screen, timeout=5000):
    page.wait_for_selector(f'#app[data-screen="{screen}"]', timeout=timeout)


def _set_threshold_ui(page, n):
    page.click("#btn-settings")
    _wait_screen(page, "settings")
    page.fill("#threshold-input", str(n))
    page.click("#btn-back")
    _wait_screen(page, "start")


def _start(page):
    page.click("#btn-start")
    _wait_screen(page, "listening")


def _samples(page, n=5, gap_ms=150):
    out = []
    for _ in range(n):
        out.append(level_value(page))
        page.wait_for_timeout(gap_ms)
    return out


# ---------- 行為 1 ----------

def test_b1_real_start_opens_mic_with_raw_constraints_audiocontext_wakelock(real_page):
    page = real_page("silence")
    assert page.get_attribute("#app", "data-screen") == "start"
    _start(page)
    gum = page.evaluate("() => window.__gum.map(g => g.c)")
    assert len(gum) >= 1, "按開始要呼叫 getUserMedia"
    audio = gum[0]["audio"]
    assert isinstance(audio, dict), f"audio 參數要是物件：{gum[0]}"
    assert audio.get("echoCancellation") is False
    assert audio.get("noiseSuppression") is False
    assert audio.get("autoGainControl") is False
    assert page.evaluate("() => window.__ac") >= 1, "要建 AudioContext"
    assert page.evaluate("() => window.__wl.requested") >= 1, "要要 Wake Lock"


DENY_SCRIPT = """
navigator.mediaDevices.getUserMedia = () =>
  Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));
"""


def test_b1_permission_denied_shows_red_text_and_stays_on_start(real_page):
    page = real_page("silence", extra_init=DENY_SCRIPT)
    page.click("#btn-start")
    page.wait_for_function(
        "t => (document.querySelector('#error-text')||{}).textContent?.includes(t)", arg=DENIED_TEXT, timeout=5000
    )
    assert page.is_visible("#error-text")
    page.wait_for_timeout(500)
    assert page.get_attribute("#app", "data-screen") == "start"


# ---------- 行為 2 ----------

def test_b2_real_loud_sine_level_above_60(real_page):
    page = real_page("loud")
    _set_threshold_ui(page, 100)
    _start(page)
    page.wait_for_function(
        "() => +((document.querySelector('#level-value')||{}).textContent||'0').trim() > 60", timeout=8000
    )
    vals = _samples(page)
    assert all(v > 60 for v in vals), f"大聲正弦波音量應 > 60：{vals}"
    assert all(0 <= v <= 100 for v in vals)


def test_b2_real_silence_level_below_10(real_page):
    page = real_page("silence")
    _set_threshold_ui(page, 100)
    _start(page)
    page.wait_for_timeout(2500)
    vals = _samples(page)
    assert all(v < 10 for v in vals), f"靜音音量應 < 10：{vals}"
    assert page.get_attribute("#app", "data-screen") == "listening"


# 已知振幅的正弦波直接當麥克風 stream：RMS＝A/√2，驗證 -70 dBFS＝0、-10 dBFS＝100 線性對應
OSC_SCRIPT = """
navigator.mediaDevices.getUserMedia = async () => {
  const ctx = new AudioContext();
  await ctx.resume();
  const osc = ctx.createOscillator();
  osc.frequency.value = 440;
  const g = ctx.createGain();
  g.gain.value = %(amp)r;
  const dest = ctx.createMediaStreamDestination();
  osc.connect(g).connect(dest);
  osc.start();
  return dest.stream;
};
"""


def _amp_for_level(level):
    dbfs = -70 + level * 60 / 100
    return math.sqrt(2) * 10 ** (dbfs / 20)


@pytest.mark.parametrize("target", [50, 80])
def test_b2_level_maps_dbfs_linearly(real_page, target):
    page = real_page("silence", extra_init=OSC_SCRIPT % {"amp": _amp_for_level(target)})
    _set_threshold_ui(page, 100)
    _start(page)
    page.wait_for_timeout(2500)  # EMA α=0.3、每 100ms：2 秒後殘差 < 0.1%
    vals = _samples(page)
    assert all(abs(v - target) <= 3 for v in vals), f"預期音量≈{target}（{-70 + target * 0.6:.0f} dBFS），實得 {vals}"


# ---------- 行為 4（真實管線端到端） ----------

def test_b4_real_loud_input_triggers_alarm(real_page):
    page = real_page("loud")
    _start(page)  # 預設門檻 65、吵 1 秒就響
    _wait_screen(page, "alarm", timeout=6000)


# ---------- 行為 6 ----------

def test_b6_real_stop_closes_mic_and_releases_wake_lock(real_page):
    page = real_page("silence")
    _start(page)
    page.wait_for_timeout(500)
    page.click("#btn-stop")
    _wait_screen(page, "start")
    page.wait_for_timeout(300)
    ended = page.evaluate(
        "() => window.__gum.length > 0 && window.__gum.every(g => g.s.getTracks().every(t => t.readyState === 'ended'))"
    )
    assert ended, "停止要關掉麥克風（所有 track stop）"
    assert page.evaluate("() => window.__wl.released") >= 1, "停止要放掉 Wake Lock"
