from kotoha.operate.stats import OperationStats


def test_counts_and_failures():
    s = OperationStats()
    s.record("intents")
    s.record("intents")
    s.record("grounded")
    s.record("executed")
    s.record("confirmed_pending")
    s.record_failure("ground")
    s.record_ground_ms(1200.0)
    s.record_ground_ms(800.0)
    snap = s.snapshot()
    assert snap["intents"] == 2
    assert snap["executed"] == 1
    assert snap["confirmed_pending"] == 1
    assert snap["failures"]["ground"] == 1
    assert snap["avg_ground_ms"] == 1000.0


def test_summary_line_is_human_readable():
    s = OperationStats()
    s.record("intents")
    s.record("executed")
    s.record("expired")
    line = s.summary_line()
    assert "intents=1" in line and "exec=1" in line and "expired=1" in line
