"""v1.1 電腦浮動小視窗（F1～F5；測試模式 ?test=1＋page.clock，Chromium）。

合約：brain-2026-09/projects/quiet-alarm/spec-v1.1.md 的「行為」與「測試介面」。
F6（背景節流）、F7（sw.js VERSION）不在這裡，DQV 模式 B 驗。

假 documentPictureInPicture（照 spec「測試用假 API」）：
  - init script 定義 window.documentPictureInPicture = { requestWindow(opts) → Promise<Window>, window }。
  - requestWindow 回傳頁面內一個 iframe 的 contentWindow；iframe 固定在主頁置中版面（最大 480px）右邊，不蓋主頁按鈕。
  - 假 window 的 close()：先對該 window 觸發 pagehide，再移除 iframe。
  - 假 window 的 setInterval／setTimeout 交給主頁的計時器（page.clock 控得到）；關窗時一起清掉，
    之後再掛也不會跑（真的小視窗關掉後，掛在它身上的計時器也就停了）。
  - window.__pipFake 記錄：calls（每次 requestWindow 的參數）、closed（close 次數）。
"""
import time

import pytest
from playwright.sync_api import expect

from conftest import QA, SPY_SCRIPT, _new_page

PIP_FRAME_ID = "__fake-pip"

FAKE_PIP_SCRIPT = """
(() => {
  if (window.top !== window) return;
  const MODE = '__MODE__';
  const rec = window.__pipFake = { calls: [], closed: 0 };
  let current = null;
  const api = {
    get window() { return current; },
    requestWindow(opts) {
      rec.calls.push(opts === undefined ? null : JSON.parse(JSON.stringify(opts)));
      if (MODE === 'throw') throw new DOMException('fake: not allowed', 'NotAllowedError');
      if (MODE === 'reject') return Promise.reject(new DOMException('fake: rejected', 'NotAllowedError'));
      if (current) current.close();
      const f = document.createElement('iframe');
      f.id = '__FRAME__';
      f.setAttribute('style',
        'position:fixed;left:750px;top:20px;width:240px;height:140px;border:1px solid #333;z-index:2147483647;background:#fff');
      document.documentElement.appendChild(f);
      const w = f.contentWindow;
      const timers = new Set();
      let dead = false;
      w.setInterval = (fn, ms, ...a) => {
        if (dead) return 0;
        const id = window.setInterval(fn, ms, ...a); timers.add(id); return id;
      };
      w.setTimeout = (fn, ms, ...a) => {
        if (dead) return 0;
        const id = window.setTimeout(fn, ms, ...a); timers.add(id); return id;
      };
      w.clearInterval = (id) => { timers.delete(id); window.clearInterval(id); };
      w.clearTimeout = (id) => { timers.delete(id); window.clearTimeout(id); };
      w.close = () => {
        if (dead) return;
        rec.closed++;
        try { w.dispatchEvent(new w.PageTransitionEvent('pagehide', { persisted: false })); }
        catch (e) { w.dispatchEvent(new w.Event('pagehide')); }
        dead = true;
        timers.forEach((id) => { window.clearInterval(id); window.clearTimeout(id); });
        timers.clear();
        if (current === w) current = null;
        f.remove();
      };
      current = w;
      return Promise.resolve(w);
    },
  };
  Object.defineProperty(window, 'documentPictureInPicture', { configurable: true, get: () => api });
})();
"""

NO_PIP_SCRIPT = """
(() => {
  try { delete Window.prototype.documentPictureInPicture; } catch (e) {}
  try { delete window.documentPictureInPicture; } catch (e) {}
})();
"""


def _make(browser, base_url, init):
    ctx = browser.new_context(viewport={"width": 1000, "height": 844})
    ctx.add_init_script(SPY_SCRIPT)
    ctx.add_init_script(init)
    errors = []
    page = _new_page(ctx, errors)
    q = QA(ctx, page, base_url)
    q.errors = errors
    return q


def _fixture(browser, base_url, init):
    q = _make(browser, base_url, init)
    yield q
    errs = list(q.errors)
    q.ctx.close()
    assert not errs, f"page errors: {errs}"


def _fake(mode="ok"):
    return FAKE_PIP_SCRIPT.replace("__MODE__", mode).replace("__FRAME__", PIP_FRAME_ID)


@pytest.fixture
def qf(chromium, base_url):
    yield from _fixture(chromium, base_url, _fake("ok"))


@pytest.fixture(params=["reject", "throw"])
def qf_fail(request, chromium, base_url):
    yield from _fixture(chromium, base_url, _fake(request.param))


@pytest.fixture
def qf_none(chromium, base_url):
    yield from _fixture(chromium, base_url, NO_PIP_SCRIPT)


@pytest.fixture
def qf_none_webkit(webkit, base_url):
    yield from _fixture(webkit, base_url, NO_PIP_SCRIPT)


# ---------- 小工具（只讀 spec 測試介面列的東西） ----------

def has_float_button(q):
    return q.page.locator("#btn-float").count() == 1


def float_hidden(q):
    return q.page.eval_on_selector("#btn-float", "e => e.hidden")


def open_float(q):
    assert has_float_button(q), "監聽畫面沒有 #btn-float"
    q.click("#btn-float")
    q.run(100)


def pip_calls(q):
    return q.page.evaluate("() => window.__pipFake.calls")


def pip_closed(q):
    return q.page.evaluate("() => window.__pipFake.closed")


def pip_open(q):
    return q.page.evaluate("() => !!window.documentPictureInPicture.window")


def pip(q, js, arg=None):
    """在小視窗 document 上跑 js（參數 d＝document, a＝arg）；小視窗沒開回 None。"""
    return q.page.evaluate(
        "([js, a]) => { const w = window.documentPictureInPicture.window; if (!w) return null;"
        " return (new Function('d', 'a', js))(w.document, a); }",
        [js, arg],
    )


def pip_attr(q, name):
    return pip(q, "const r = d.getElementById('pip-root'); return r ? r.getAttribute(a) : null;", name)


def pip_text(q, el_id):
    t = pip(q, "const e = d.getElementById(a); return e ? e.textContent : null;", el_id)
    return None if t is None else " ".join(t.split())


def pip_root_text(q):
    t = pip(q, "const e = d.getElementById('pip-root'); return e ? (e.innerText || e.textContent) : null;")
    return None if t is None else " ".join(t.split())


def pip_fill_width(q):
    return pip(q, "const e = d.getElementById('pip-fill'); return e ? e.style.width : null;")


def pip_dots(q):
    return pip(q, "const e = d.getElementById('pip-dots'); return e ? e.querySelectorAll('.dot').length : null;")


def pip_dots_on(q):
    return pip(q, "const e = d.getElementById('pip-dots'); return e ? e.querySelectorAll('.dot.on').length : null;")


def wait_real(cond, timeout=2.0):
    """等 CSS 過場這類不受 page.clock 控制的東西（真實時間，最多 timeout 秒）。"""
    end = time.time() + timeout
    while True:
        v = cond()
        if v or time.time() > end:
            return v
        time.sleep(0.05)


def pip_shot(q, name):
    from conftest import EVIDENCE
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    loc = q.page.locator(f"#{PIP_FRAME_ID}")
    if loc.count():
        loc.screenshot(path=str(EVIDENCE / name))


# ---------- F1 按鈕 ----------

def test_f1_float_button_above_stop_with_same_style_as_stop(qf):
    qf.open()
    qf.start()
    assert has_float_button(qf), "監聽畫面沒有 #btn-float"
    btn = qf.page.locator("#btn-float")
    expect(btn).to_be_visible()
    assert "開浮動小視窗" in qf.text("#btn-float")
    fb = btn.bounding_box()
    sb = qf.page.locator("#btn-stop").bounding_box()
    assert fb["y"] + fb["height"] <= sb["y"] + 1, "#btn-float 要在 #btn-stop 上方"
    props = ["background-color", "color", "border-top-width", "border-top-style", "border-radius", "font-size", "font-weight"]
    get = "(e, ps) => { const s = getComputedStyle(e); return ps.map(p => s.getPropertyValue(p)); }"
    assert btn.evaluate(get, props) == qf.page.locator("#btn-stop").evaluate(get, props), "樣式要同 #btn-stop"


def test_f1_no_api_float_button_hidden_chromium(qf_none):
    q = qf_none
    q.open()
    assert q.page.evaluate("() => 'documentPictureInPicture' in window") is False
    q.start()
    assert has_float_button(q), "頁面上要有 #btn-float（沒有 API 時設 hidden）"
    assert float_hidden(q) is True, "沒有 documentPictureInPicture 時 #btn-float 要 hidden"
    expect(q.page.locator("#btn-float")).to_be_hidden()
    q.level(80)
    q.run(1200)
    assert q.screen() == "alarm", "沒有 API 時其他行為不變"


def test_f1_no_api_float_button_hidden_webkit(qf_none_webkit):
    q = qf_none_webkit
    q.open()
    assert q.page.evaluate("() => 'documentPictureInPicture' in window") is False
    q.start()
    assert has_float_button(q), "頁面上要有 #btn-float（沒有 API 時設 hidden）"
    assert float_hidden(q) is True, "Safari（WebKit）沒有 API → #btn-float hidden"


def test_f1_float_button_hidden_while_window_open(qf):
    qf.open()
    qf.start()
    open_float(qf)
    assert pip_open(qf), "按 #btn-float 後小視窗要開著"
    assert float_hidden(qf) is True, "小視窗開著時 #btn-float 要 hidden"


# ---------- F2 開窗 ----------

def test_f2_click_requests_window_240x140_and_shows_listening(qf):
    qf.open()
    qf.start()
    open_float(qf)
    assert pip_calls(qf) == [{"width": 240, "height": 140}]
    assert pip_attr(qf, "data-screen") == "listening"
    assert qf.screen() == "listening", "開小視窗後主頁照常監聽"
    pip_shot(qf, "f2-pip-listening.png")


def test_f2_css_written_into_window_document_not_loaded_file(qf):
    qf.open()
    qf.start()
    open_float(qf)
    assert pip_attr(qf, "data-screen") == "listening", "小視窗內容沒畫出來"
    links = pip(qf, "return d.querySelectorAll('link[rel~=stylesheet]').length;")
    assert links == 0, "小視窗不另外載 CSS 檔"
    sheets = pip(qf, "return d.styleSheets.length + (d.adoptedStyleSheets ? d.adoptedStyleSheets.length : 0);")
    assert sheets >= 1, "CSS 要直接寫進小視窗的 document"


def test_f2_open_failure_shows_error_and_keeps_listening(qf_fail):
    q = qf_fail
    q.open()
    q.start()
    open_float(q)
    q.run(100)
    assert pip_calls(q) == [{"width": 240, "height": 140}], "要呼叫 requestWindow"
    assert q.text("#error-text") == "開不了浮動小視窗"
    assert q.screen() == "listening", "開窗失敗主頁照常監聽"
    t = q.trigger_alarm()
    assert 900 <= t <= 1300, f"開窗失敗後偵測照常（預設 1 秒觸發），實際 {t}ms"


# ---------- F3 同步 ----------

@pytest.mark.parametrize("lv,mood,word", [(30, "calm", "很安靜"), (58, "warn", "有點吵"), (80, "loud", "太吵了")])
def test_f3_listening_values_match_main_page(qf, lv, mood, word):
    qf.open()
    qf.start()
    open_float(qf)
    qf.level(lv)
    qf.run(100)
    assert qf.screen() == "listening"
    assert pip_attr(qf, "data-screen") == "listening"
    assert pip_attr(qf, "data-mood") == mood == qf.mood()
    assert pip_text(qf, "pip-mood-text") == word
    assert pip_text(qf, "pip-level") == str(lv) == qf.text("#level-value")
    assert pip_fill_width(qf) == f"{lv}%"
    assert pip_text(qf, "pip-threshold") == "警報 65"
    main_color = qf.page.eval_on_selector("#level-fill", "e => getComputedStyle(e).backgroundColor")
    color = lambda: pip(qf, "const e = d.getElementById('pip-fill'); return e ? d.defaultView.getComputedStyle(e).backgroundColor : null;")
    assert wait_real(lambda: color() == main_color), f"音量條顏色要和主頁一樣：小視窗 {color()}、主頁 {main_color}"


def test_f3_level_follows_each_tick(qf):
    qf.open()
    qf.start()
    open_float(qf)
    for lv in (12, 47, 33):
        qf.level(lv)
        qf.run(100)
        assert pip_text(qf, "pip-level") == str(lv) == qf.text("#level-value")
        assert pip_fill_width(qf) == f"{lv}%"


def test_f3_settings_screen_keeps_listening_view_and_threshold_follows(qf):
    qf.open()
    qf.start()
    open_float(qf)
    qf.settings()
    qf.level(45)
    qf.run(100)
    assert pip_attr(qf, "data-screen") == "listening", "主頁進設定時小視窗照常顯示監聽中"
    assert pip_text(qf, "pip-level") == "45"
    assert pip_attr(qf, "data-mood") == "calm"  # 門檻 65：45 < 52
    qf.set_threshold(50)
    qf.run(100)
    assert pip_text(qf, "pip-threshold") == "警報 50", "改門檻後小視窗門檻跟著變"
    assert pip_attr(qf, "data-mood") == "warn"  # 門檻 50：40 ≤ 45 < 50
    assert pip_text(qf, "pip-mood-text") == "有點吵"


def test_f3_alarm_view_and_dots_match_main_page(qf):
    qf.open()
    qf.start()
    open_float(qf)
    qf.trigger_alarm()
    assert pip_attr(qf, "data-screen") == "alarm"
    assert "請安靜！" in (pip_root_text(qf) or "")
    assert pip_text(qf, "pip-dismiss") == "解除"
    assert pip_dots(qf) == 3 == qf.dots(), "圓點數＝安靜幾秒解除（預設 3）"
    assert pip_dots_on(qf) == 0
    pip_shot(qf, "f3-pip-alarm.png")
    qf.level(10)
    qf.run(3400)  # 播完後安靜 1.4s
    assert qf.dots_on() == 1
    assert pip_dots_on(qf) == qf.dots_on()
    qf.run(1000)
    assert pip_dots_on(qf) == qf.dots_on() == 2
    qf.run(1000)
    assert qf.screen() == "listening"
    assert pip_attr(qf, "data-screen") == "listening", "主頁回監聽，小視窗也回監聽"


def test_f3_alarm_dot_count_follows_quiet_setting(qf):
    qf.open()
    qf.settings()
    qf.choose("quiet", "5")
    qf.back()
    qf.start()
    open_float(qf)
    qf.trigger_alarm()
    assert pip_dots(qf) == 5 == qf.dots()


def test_f3_stop_shows_stopped_in_window(qf):
    qf.open()
    qf.start()
    open_float(qf)
    qf.click("#btn-stop")
    qf.run(100)
    assert qf.screen() == "start"
    assert pip_open(qf), "主頁按停止時小視窗不關"
    assert pip_attr(qf, "data-screen") == "stopped"
    txt = pip_root_text(qf) or ""
    assert "已停止" in txt and "回主頁按開始" in txt, f"小視窗要顯示「已停止」＋「回主頁按開始」，實際：{txt!r}"
    pip_shot(qf, "f3-pip-stopped.png")


# ---------- F4 解除 ----------

def test_f4_window_dismiss_equals_main_dismiss(qf):
    qf.open()
    qf.start()
    open_float(qf)
    qf.trigger_alarm()
    qf.level(90)
    qf.run(500)
    assert pip_attr(qf, "data-screen") == "alarm"
    qf.page.frame_locator(f"#{PIP_FRAME_ID}").locator("#pip-dismiss").click()
    qf.run(0)
    assert qf.screen() == "listening", "按小視窗的解除＝按主頁解除，立刻回監聽"
    assert pip_attr(qf, "data-screen") == "listening"
    qf.run(800)
    assert qf.screen() == "listening", "回監聽後觸發計時從 0 開始"
    qf.run(500)
    assert qf.screen() == "alarm"


# ---------- F5 關窗 ----------

def test_f5_user_close_keeps_listening_and_button_returns(qf):
    qf.open()
    qf.start()
    open_float(qf)
    assert pip_open(qf)
    qf.page.evaluate("() => window.documentPictureInPicture.window.close()")
    qf.run(100)
    assert not pip_open(qf)
    assert qf.screen() == "listening", "關掉小視窗主頁照常監聽"
    assert has_float_button(qf)
    assert float_hidden(qf) is False, "關掉小視窗後 #btn-float 重新出現"
    expect(qf.page.locator("#btn-float")).to_be_visible()
    qf.level(30)
    qf.run(300)
    assert qf.text("#level-value") == "30", "關窗後音量照常更新"
    t = qf.trigger_alarm()
    assert 900 <= t <= 1300, f"關窗後偵測照常（預設 1 秒觸發），實際 {t}ms"


def test_f5_can_reopen_after_close(qf):
    qf.open()
    qf.start()
    open_float(qf)
    qf.page.evaluate("() => window.documentPictureInPicture.window.close()")
    qf.run(100)
    open_float(qf)
    assert len(pip_calls(qf)) == 2, "關掉後可以再開"
    assert pip_open(qf)
    qf.level(58)
    qf.run(100)
    assert pip_attr(qf, "data-screen") == "listening"
    assert pip_text(qf, "pip-level") == "58"
    assert pip_attr(qf, "data-mood") == "warn"
    assert float_hidden(qf) is True


def test_f5_stop_keeps_window_then_start_returns_to_listening(qf):
    qf.open()
    qf.start()
    open_float(qf)
    qf.click("#btn-stop")
    qf.run(100)
    assert pip_closed(qf) == 0 and pip_open(qf), "按停止小視窗不關"
    assert pip_attr(qf, "data-screen") == "stopped"
    qf.start()
    assert pip_attr(qf, "data-screen") == "listening", "再按開始後小視窗回到監聽樣子"
    assert float_hidden(qf) is True, "小視窗還開著，#btn-float 維持 hidden"
    qf.level(80)
    qf.run(100)
    assert pip_text(qf, "pip-level") == "80"
    assert pip_attr(qf, "data-mood") == "loud"
