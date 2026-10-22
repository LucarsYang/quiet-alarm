"""行為 7：設定（測試模式 ?test=1＋page.clock，Chromium）。"""
import json

import pytest

SETTINGS_KEY = "quiet-alarm-settings"


def test_b7_defaults(qa):
    qa.open()
    qa.settings()
    assert qa.threshold() == 65
    assert qa.page.get_attribute("#threshold-input", "type") == "range"
    assert qa.page.get_attribute("#threshold-input", "min") in ("0", None)  # range 預設 min=0
    assert qa.page.get_attribute("#threshold-input", "max") in ("100", None)  # range 預設 max=100
    assert qa.checked("sustain") == "1"
    assert qa.checked("sound") == "voice"
    assert qa.checked("quiet") == "3"
    assert sorted(qa.page.eval_on_selector_all('input[name="sustain"]', "es => es.map(e => e.value)")) == ["0.5", "1", "2"]
    assert sorted(qa.page.eval_on_selector_all('input[name="sound"]', "es => es.map(e => e.value)")) == ["beep", "custom", "none", "voice"]
    assert sorted(qa.page.eval_on_selector_all('input[name="quiet"]', "es => es.map(e => e.value)"), key=int) == ["2", "3", "5"]
    qa.shot("b7-settings.png")


def test_b7_settings_from_start_and_back(qa):
    qa.open()
    qa.settings()
    qa.back()
    assert qa.screen() == "start"


def test_b7_settings_from_listening_and_back(qa):
    qa.open()
    qa.start()
    qa.settings()
    qa.back()
    assert qa.screen() == "listening"


def test_b7_threshold_slider_updates_label(qa):
    qa.open()
    qa.settings()
    qa.set_threshold(40)
    assert qa.threshold() == 40
    qa.back()
    qa.start()
    assert "警報 40" in qa.text("#threshold-label")


def test_b7_use_current_disabled_before_start(qa):
    qa.open()
    qa.settings()
    assert qa.page.is_disabled("#btn-use-current"), "未開始時不能按"


def test_b7_use_current_disabled_again_after_stop(qa):
    qa.open()
    qa.start()
    qa.click("#btn-stop")
    qa.run(100)
    qa.settings()
    assert qa.page.is_disabled("#btn-use-current")


def test_b7_use_current_sets_avg_plus_15(qa):
    qa.open()
    qa.start()
    qa.level(40)
    qa.run(2500)  # 最近 2 秒都是 40
    qa.settings()
    assert qa.page.is_enabled("#btn-use-current")
    qa.click("#btn-use-current")
    assert qa.threshold() == 55
    qa.back()
    assert "警報 55" in qa.text("#threshold-label")


def test_b7_use_current_uses_last_2s_average(qa):
    qa.open()
    qa.start()
    qa.level(10)
    qa.run(3000)
    qa.level(30)
    qa.run(1000)
    qa.level(50)
    qa.run(1000)  # 最近 2 秒：30 一半、50 一半 → 平均 40
    qa.settings()
    qa.click("#btn-use-current")
    assert abs(qa.threshold() - 55) <= 1, f"門檻應≈40+15，實得 {qa.threshold()}"


def test_b7_use_current_caps_at_95(qa):
    qa.open()
    qa.start()
    qa.settings()  # 設定畫面不觸發，才能維持 90 超過 2 秒
    qa.level(90)
    qa.run(2500)
    qa.click("#btn-use-current")
    assert qa.threshold() == 95


@pytest.mark.parametrize("sound", ["voice", "beep", "none"])
def test_b7_record_button_hidden_unless_custom(qa, sound):
    qa.open()
    qa.settings()
    qa.choose("sound", sound)
    rec = qa.page.locator("#btn-record")
    assert rec.count() == 0 or not rec.is_visible()


def test_b7_record_button_shown_for_custom(qa):
    qa.open()
    qa.settings()
    qa.choose("sound", "custom")
    assert qa.page.is_visible("#btn-record")


def test_b7_settings_persist_after_reopen(qa):
    qa.open()
    qa.settings()
    qa.set_threshold(40)
    qa.choose("sustain", "2")
    qa.choose("sound", "beep")
    qa.choose("quiet", "5")
    qa.back()
    raw = qa.page.evaluate(f"() => localStorage.getItem('{SETTINGS_KEY}')")
    assert raw, f"localStorage 沒有 {SETTINGS_KEY}"
    json.loads(raw)  # 存的要是 JSON

    qa.reopen()
    qa.settings()
    assert qa.threshold() == 40
    assert qa.checked("sustain") == "2"
    assert qa.checked("sound") == "beep"
    assert qa.checked("quiet") == "5"
    qa.back()

    # 重開後的設定真的生效
    qa.start()
    assert "警報 40" in qa.text("#threshold-label")
    qa.level(60)
    qa.run(1500)
    assert qa.screen() == "listening", "吵多久才響＝2 秒"
    qa.run(800)
    assert qa.screen() == "alarm"
    assert qa.played() == ["beep"]
    assert qa.dots() == 5


def test_b7_use_current_result_persists(qa):
    qa.open()
    qa.start()
    qa.level(40)
    qa.run(2500)
    qa.settings()
    qa.click("#btn-use-current")
    qa.back()
    qa.reopen()
    qa.settings()
    assert qa.threshold() == 55
