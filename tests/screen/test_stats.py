from kotoha.screen.stats import PerceptionStats


def test_counts_and_failures():
    s = PerceptionStats()
    s.record_capture(100.0)
    s.record_capture(200.0)
    s.record_describe(5000.0)
    s.record_skip()
    s.record_skip()
    s.record_summary_update()
    s.record_failure("vlm")
    snap = s.snapshot()
    assert snap["captures"] == 2
    assert snap["describes"] == 1
    assert snap["skips"] == 2
    assert snap["summary_updates"] == 1
    assert snap["failures"] == {"capture": 0, "vlm": 1}


def test_averages_and_last():
    s = PerceptionStats()
    s.record_capture(100.0)
    s.record_capture(300.0)
    s.record_describe(4000.0)
    s.record_describe(8000.0)
    snap = s.snapshot()
    assert snap["last_capture_ms"] == 300.0
    assert snap["avg_capture_ms"] == 200.0
    assert snap["last_vlm_ms"] == 8000.0
    assert snap["avg_vlm_ms"] == 6000.0


def test_averages_zero_when_empty():
    snap = PerceptionStats().snapshot()
    assert snap["avg_capture_ms"] == 0.0
    assert snap["avg_vlm_ms"] == 0.0
    assert snap["mode"] == "normal"


def test_summary_line_is_human_readable():
    s = PerceptionStats()
    s.record_describe(6000.0)
    s.set_mode("game_powersave")
    line = s.summary_line()
    assert "describes=1" in line
    assert "vlm_avg=6.0s" in line
    assert "mode=game_powersave" in line
