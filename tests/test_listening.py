"""行為 1、2、3、4、6：開始、音量顯示、心情、觸發、停止（測試模式 ?test=1＋page.clock，Chromium）。"""
import pytest



# ---------- 行為 1：開始畫面 → 監聽（測試模式不開麥克風、不要 Wake Lock） ----------

def test_b1_start_screen_then_listening(qa):
    qa.open()
    assert qa.screen() == "start"
    qa.start()
    assert qa.screen() == "listening"
    err = qa.page.locator("#error-text")
    assert err.count() == 0 or not err.is_visible() or err.inner_text().strip() == "", "沒錯誤時不該有紅字"
    qa.shot("b1-listening.png")


def test_b1_test_mode_does_not_touch_mic_or_wake_lock(qa):
    qa.open()
    qa.start()
    qa.run(1000)
    spy = qa.page.evaluate("() => window.__spy")
    assert spy["gum"] == 0, "測試模式不該呼叫 getUserMedia"
    assert spy["wake"] == 0, "測試模式不該要 Wake Lock"


# ---------- 行為 2：音量顯示為整數（設定平滑後音量） ----------

@pytest.mark.parametrize("n", [0, 42, 100])
def test_b2_level_value_shows_integer(qa, n):
    qa.open()
    qa.start()
    qa.level(n)
    qa.run(200)
    assert qa.text("#level-value") == str(n)


# ---------- 行為 3：心情 calm／warn／loud 邊界 ----------

MOOD_TEXT = {"calm": "很安靜", "warn": "有點吵", "loud": "太吵了"}


@pytest.mark.parametrize(
    "lv,mood",
    [(0, "calm"), (51, "calm"), (52, "warn"), (64, "warn"), (65, "loud"), (100, "loud")],
)
def test_b3_mood_boundaries_default_threshold_65(qa, lv, mood):
    qa.open()
    qa.start()
    assert "警報 65" in qa.text("#threshold-label")
    qa.level(lv)
    qa.run(200)  # 小於「吵多久才響」1 秒，不會進警報
    assert qa.screen() == "listening"
    assert qa.mood() == mood
    assert MOOD_TEXT[mood] in qa.text("#mood-text")


def test_b3_mood_follows_changed_threshold(qa):
    qa.open()
    qa.settings()
    qa.set_threshold(40)
    qa.back()
    qa.start()
    assert "警報 40" in qa.text("#threshold-label")
    for lv, mood in [(31, "calm"), (32, "warn"), (39, "warn"), (40, "loud")]:
        qa.level(lv)
        qa.run(200)
        assert qa.mood() == mood, f"門檻 40、音量 {lv} 應為 {mood}"
        qa.level(0)
        qa.run(200)


# ---------- 行為 4：觸發 ----------

def test_b4_trigger_after_default_1s(qa):
    qa.open()
    qa.start()
    qa.level(80)
    qa.run(800)
    assert qa.screen() == "listening", "未滿 1 秒不該響"
    qa.run(500)
    assert qa.screen() == "alarm"


@pytest.mark.parametrize("sustain,ms", [("0.5", 500), ("2", 2000)])
def test_b4_trigger_respects_sustain_setting(qa, sustain, ms):
    qa.open()
    qa.settings()
    qa.choose("sustain", sustain)
    qa.back()
    qa.start()
    qa.level(80)
    qa.run(ms - 200)
    assert qa.screen() == "listening"
    qa.run(500)
    assert qa.screen() == "alarm"


def test_b4_exactly_threshold_counts_as_loud(qa):
    qa.open()
    qa.start()
    qa.level(65)
    qa.run(1300)
    assert qa.screen() == "alarm", "≥ 門檻就算吵"


def test_b4_dip_below_threshold_resets_count(qa):
    qa.open()
    qa.start()
    qa.level(80)
    qa.run(700)
    qa.level(64)  # 一次低於門檻
    qa.run(200)
    qa.level(80)
    qa.run(700)
    assert qa.screen() == "listening", "中間低於門檻要重算"
    qa.run(600)
    assert qa.screen() == "alarm"


def test_b4_no_trigger_while_in_settings(qa):
    qa.open()
    qa.start()
    qa.settings()
    qa.level(95)
    qa.run(3000)
    assert qa.screen() == "settings", "在設定畫面時不觸發"
    assert qa.played() == []
    qa.back()
    assert qa.screen() == "listening"


# ---------- 行為 6：停止 ----------

def test_b6_stop_returns_to_start(qa):
    qa.open()
    qa.start()
    qa.level(30)
    qa.run(300)
    qa.click("#btn-stop")
    qa.run(100)
    assert qa.screen() == "start"
    # 停止後不再偵測：大聲也不會進警報
    qa.level(95)
    qa.run(3000)
    assert qa.screen() == "start"
    assert qa.played() == []


def test_b6_can_start_again_after_stop(qa):
    qa.open()
    qa.start()
    qa.click("#btn-stop")
    qa.run(100)
    qa.start()
    qa.trigger_alarm()
