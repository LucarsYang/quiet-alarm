"""WebKit（iPhone Safari 引擎）跑主流程一條：開始 → 心情 → 觸發 → 警報 → 安靜解除 → 停止。測試模式＋page.clock。"""


def test_webkit_main_flow(qa_webkit):
    qa = qa_webkit
    qa.open()
    assert qa.screen() == "start"
    qa.start()

    qa.level(30)
    qa.run(200)
    assert qa.mood() == "calm"
    assert qa.text("#level-value") == "30"

    qa.level(60)
    qa.run(200)
    assert qa.mood() == "warn"

    qa.trigger_alarm(loud=85)
    assert qa.screen() == "alarm"
    assert qa.played() == ["voice"]
    assert qa.dots() == 3
    qa.shot("webkit-alarm.png")

    qa.level(10)
    qa.run(3400)
    assert qa.dots_on() == 1
    qa.run(2000)
    assert qa.screen() == "listening"

    qa.trigger_alarm(loud=85)
    qa.click("#btn-dismiss")
    assert qa.screen() == "listening"

    qa.click("#btn-stop")
    qa.run(100)
    assert qa.screen() == "start"
