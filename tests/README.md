# 安靜警報驗收測試（凍結）

合約：`~/Documents/brain-2026-09/projects/quiet-alarm/spec.md` 的「行為」與「測試介面」兩節。測試只用那裡列出的 DOM id、`data-screen`／`data-mood`、`?test=1` 與 `window.__qa`，不依賴實作細節。實作讓這些測試全綠即可，**不要改測試**；覺得測試和規格不符，回報主對談。

## 怎麼跑

```
cd ~/Documents/workspace/quiet-alarm/app
python3 -m pytest tests -q                 # 全部
python3 -m pytest tests -q -k real         # 只跑真實管線
python3 -m pytest tests -q -k webkit       # 只跑 WebKit 主流程
```

- conftest 用 `python3 -m http.server` 在隨機埠服務 `app/`（service worker 需要 http）。
- Chromium：python playwright 對應版本沒裝時，自動改用 `~/Library/Caches/ms-playwright` 裡最新的 chromium headless shell。
- 截圖寫到 `~/Documents/workspace/quiet-alarm/evidence/`（repo 外）。
- 測試模式測試：裝 `page.clock` 後停住，只靠 `run_for` 推進；音量用 `__qa.setLevel(n)`，聲音看 `__qa.played`（每次播放視為 2 秒）。
- 真實管線測試：不帶 `?test=1`、真實時間；Chromium 帶 `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>`。wav 由 conftest 產生：大聲正弦波（振幅 0.25，約 -15 dBFS → 音量約 92）與數位靜音。headless 沒有 Wake Lock，所以換成記錄用的假物件；getUserMedia／AudioContext 只包一層記錄。

## 測試對應規格

| 規格 | 測試（檔案::函式） |
|---|---|
| 1 開始→監聽 | `test_listening.py::test_b1_start_screen_then_listening` |
| 1 開麥克風參數、AudioContext、Wake Lock | `test_real_pipeline.py::test_b1_real_start_opens_mic_with_raw_constraints_audiocontext_wakelock` |
| 1 拒絕權限：紅字、留在開始 | `test_real_pipeline.py::test_b1_permission_denied_shows_red_text_and_stays_on_start` |
| 測試介面：測試模式不開麥克風、不要 Wake Lock | `test_listening.py::test_b1_test_mode_does_not_touch_mic_or_wake_lock` |
| 2 音量整數顯示 | `test_listening.py::test_b2_level_value_shows_integer`（0／42／100） |
| 2 dBFS 線性對應（-70＝0、-10＝100） | `test_real_pipeline.py::test_b2_level_maps_dbfs_linearly`（已知振幅正弦波，目標 50、80，誤差 ±3） |
| 2／測試介面 真實管線：大聲 > 60、靜音 < 10 | `test_real_pipeline.py::test_b2_real_loud_sine_level_above_60`、`test_b2_real_silence_level_below_10` |
| 3 心情邊界（門檻 65：51 calm、52 warn、64 warn、65 loud）＋文字 | `test_listening.py::test_b3_mood_boundaries_default_threshold_65` |
| 3 心情跟著改過的門檻 | `test_listening.py::test_b3_mood_follows_changed_threshold` |
| 4 預設吵 1 秒才響 | `test_listening.py::test_b4_trigger_after_default_1s`、`test_b4_exactly_threshold_counts_as_loud` |
| 4 吵多久 0.5／2 秒 | `test_listening.py::test_b4_trigger_respects_sustain_setting` |
| 4 中間低於門檻重算 | `test_listening.py::test_b4_dip_below_threshold_resets_count` |
| 4 設定畫面不觸發 | `test_listening.py::test_b4_no_trigger_while_in_settings` |
| 4 真實輸入端到端觸發 | `test_real_pipeline.py::test_b4_real_loud_input_triggers_alarm` |
| 5 警報畫面、預設播 voice、圓點數 3 | `test_alarm.py::test_b5_alarm_screen_plays_voice_by_default` |
| 5 播放期間不偵測、每安靜 1 秒亮一顆、亮滿回監聽 | `test_alarm.py::test_b5_no_detection_during_playback_then_dots_light_each_quiet_second`、`test_b5_loud_during_playback_is_ignored` |
| 5 中途吵就全部歸零 | `test_alarm.py::test_b5_loud_midway_resets_all_dots` |
| 5 解除立刻回監聽、觸發計時從 0 | `test_alarm.py::test_b5_dismiss_returns_immediately_and_trigger_restarts_from_zero`、`test_b5_after_auto_release_trigger_restarts_from_zero` |
| 5 圓點數＝安靜幾秒解除（2、5） | `test_alarm.py::test_b5_dot_count_follows_quiet_setting` |
| 5 警報聲 beep／none／custom 沒錄過改 beep | `test_alarm.py::test_b5_sound_beep`、`test_b5_sound_none_plays_nothing`、`test_b5_custom_without_recording_falls_back_to_beep` |
| 6 停止回開始、不再偵測、可再開始 | `test_listening.py::test_b6_stop_returns_to_start`、`test_b6_can_start_again_after_stop` |
| 6 停止關麥克風、放 Wake Lock | `test_real_pipeline.py::test_b6_real_stop_closes_mic_and_releases_wake_lock` |
| 7 預設值與選項 | `test_settings.py::test_b7_defaults` |
| 7 開始／監聽都進得去、返回原畫面 | `test_settings.py::test_b7_settings_from_start_and_back`、`test_b7_settings_from_listening_and_back` |
| 7 門檻拉桿與「警報 N」 | `test_settings.py::test_b7_threshold_slider_updates_label` |
| 7 用現在的音量（未開始 disabled、平均＋15、最近 2 秒、上限 95、會保存） | `test_settings.py::test_b7_use_current_*` |
| 7 錄音鈕只在 custom 出現 | `test_settings.py::test_b7_record_button_hidden_unless_custom`、`test_b7_record_button_shown_for_custom` |
| 7 設定存 localStorage、重開保留且生效 | `test_settings.py::test_b7_settings_persist_after_reopen` |
| 主流程（WebKit） | `test_webkit.py::test_webkit_main_flow` |

## 沒有自動化的部分（要人工或主對談實機驗）

- 5 全螢幕紅閃、beep 880Hz 三聲約 1.5 秒、voice 實際聲音：合約沒有可觀察的 hook。
- 7 黃色即時音量條：合約沒有給 DOM id。
- 7 custom 錄音 3 秒、存 IndexedDB、試聽、錄過後警報播 `custom`：測試模式不開麥克風，合約也沒有錄音完成的 hook 與試聽鈕 id。
- 8 iPhone（播放時停麥克風再重開、visibilitychange 重要 Wake Lock、麥克風斷線提示）、9 manifest／service worker 離線：不在這批（任務只涵蓋 1～7），需實機驗。
