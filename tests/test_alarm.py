"""行為 5：警報（測試模式 ?test=1＋page.clock，Chromium）。

時間軸（每次播放視為 2 秒，播完才開始數安靜）：
  進警報 t=0 → 播放到 2.0s → 每連續安靜 1 秒亮一顆 → 預設 3 顆亮滿回監聽（約 5.0s）。
檢查點刻意離邊界 ≥0.4s，容許 100ms tick 的誤差。
"""
import pytest


def test_b5_alarm_screen_plays_voice_by_default(qa):
    qa.open()
    qa.start()
    qa.trigger_alarm()
    assert qa.screen() == "alarm"
    assert qa.played() == ["voice"]
    assert qa.dots() == 3, "預設安靜 3 秒解除 → 3 顆圓點"
    assert qa.dots_on() == 0
    qa.shot("b5-alarm.png")


def test_b5_no_detection_during_playback_then_dots_light_each_quiet_second(qa):
    qa.open()
    qa.start()
    qa.trigger_alarm()
    qa.level(10)  # 一進警報就安靜
    qa.run(1800)
    assert qa.dots_on() == 0, "播放期間（2 秒）不偵測，不該亮圓點"
    qa.run(1600)  # 3.4s：播完後安靜 1.4s
    assert qa.dots_on() == 1
    qa.run(1000)  # 4.4s
    assert qa.dots_on() == 2
    assert qa.screen() == "alarm"
    qa.run(1000)  # 5.4s：3 顆亮滿
    assert qa.screen() == "listening"
    assert qa.played() == ["voice"], "警報只播一次"


def test_b5_loud_during_playback_is_ignored(qa):
    qa.open()
    qa.start()
    qa.trigger_alarm()
    qa.level(95)  # 播放期間很吵（含播放的警報聲本身）
    qa.run(1800)
    assert qa.screen() == "alarm"
    assert qa.played() == ["voice"], "播放期間不偵測，不會再觸發一次"
    qa.level(10)
    qa.run(3600)  # 5.4s
    assert qa.screen() == "listening"


def test_b5_loud_midway_resets_all_dots(qa):
    qa.open()
    qa.start()
    qa.trigger_alarm()
    qa.level(10)
    qa.run(4400)  # 2 顆亮
    assert qa.dots_on() == 2
    qa.level(80)
    qa.run(300)
    assert qa.dots_on() == 0, "中途 ≥ 門檻要全部歸零"
    assert qa.screen() == "alarm"
    qa.level(10)
    qa.run(2600)  # 歸零後只安靜 2.6s
    assert qa.screen() == "alarm"
    assert qa.dots_on() == 2
    qa.run(800)  # 3.4s
    assert qa.screen() == "listening"


def test_b5_dismiss_returns_immediately_and_trigger_restarts_from_zero(qa):
    qa.open()
    qa.start()
    qa.trigger_alarm()
    qa.level(90)  # 一直很吵
    qa.run(500)
    qa.click("#btn-dismiss")
    assert qa.screen() == "listening", "按解除立刻回監聽"
    qa.run(800)
    assert qa.screen() == "listening", "回監聽後觸發計時從 0 開始"
    qa.run(500)
    assert qa.screen() == "alarm"
    assert qa.played() == ["voice", "voice"]


def test_b5_after_auto_release_trigger_restarts_from_zero(qa):
    qa.open()
    qa.start()
    qa.trigger_alarm()
    qa.level(10)
    qa.run(5400)
    assert qa.screen() == "listening"
    qa.level(90)
    qa.run(800)
    assert qa.screen() == "listening"
    qa.run(500)
    assert qa.screen() == "alarm"


@pytest.mark.parametrize("quiet", [2, 5])
def test_b5_dot_count_follows_quiet_setting(qa, quiet):
    qa.open()
    qa.settings()
    qa.choose("quiet", str(quiet))
    qa.back()
    qa.start()
    qa.trigger_alarm()
    assert qa.dots() == quiet
    qa.level(10)
    qa.run(2000 + quiet * 1000 - 600)
    assert qa.screen() == "alarm"
    assert qa.dots_on() == quiet - 1
    qa.run(1000)
    assert qa.screen() == "listening"


def test_b5_sound_beep(qa):
    qa.open()
    qa.settings()
    qa.choose("sound", "beep")
    qa.back()
    qa.start()
    qa.trigger_alarm()
    assert qa.played() == ["beep"]


def test_b5_sound_none_plays_nothing(qa):
    qa.open()
    qa.settings()
    qa.choose("sound", "none")
    qa.back()
    qa.start()
    qa.trigger_alarm()
    assert qa.screen() == "alarm"
    qa.level(10)
    qa.run(6000)
    assert qa.played() == []
    assert qa.screen() == "listening", "不出聲也要能靠安靜解除"


def test_b5_custom_without_recording_falls_back_to_beep(qa):
    qa.open()
    qa.settings()
    qa.choose("sound", "custom")
    qa.back()
    qa.start()
    qa.trigger_alarm()
    assert qa.played() == ["beep"], "選 custom 但沒錄過 → 改播 beep"
