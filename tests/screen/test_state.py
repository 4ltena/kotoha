from kotoha.screen.state import ScreenContext


class _Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_summary_roundtrip_and_staleness():
    clk = _Clock()
    ctx = ScreenContext(summary_max_age_s=10.0, clock=clk)
    assert ctx.get_summary() is None          # 未設定は None
    ctx.set_summary("  画面にエディタが映っている。 ")
    assert ctx.get_summary() == "画面にエディタが映っている。"   # strip 済み
    clk.t += 5.0
    assert ctx.get_summary() == "画面にエディタが映っている。"   # 期限内
    clk.t += 6.0
    assert ctx.get_summary() is None          # 期限切れ


def test_empty_summary_is_none():
    ctx = ScreenContext(clock=_Clock())
    ctx.set_summary("   ")
    assert ctx.get_summary() is None


def test_mode_and_background_gate():
    ctx = ScreenContext(clock=_Clock())
    assert ctx.mode == "normal"
    assert ctx.background_llm_allowed() is True
    ctx.set_mode("game_powersave")
    assert ctx.mode == "game_powersave"
    assert ctx.background_llm_allowed() is False
    ctx.set_mode("game_realtime")
    assert ctx.background_llm_allowed() is True
