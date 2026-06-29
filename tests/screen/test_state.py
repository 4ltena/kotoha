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


def test_touch_refreshes_freshness_without_changing_content():
    clk = _Clock()
    ctx = ScreenContext(summary_max_age_s=10.0, clock=clk)
    ctx.set_summary("画面にエディタ。")
    clk.t += 8.0
    ctx.touch()                # 期限切れ前に鮮度更新
    clk.t += 8.0               # 元の set からは 16s 経過(>10)だが touch から 8s
    assert ctx.get_summary() == "画面にエディタ。"   # まだ有効、内容も不変
    clk.t += 5.0               # touch から 13s で期限切れ
    assert ctx.get_summary() is None


def test_touch_is_noop_without_summary():
    ctx = ScreenContext(clock=_Clock())
    ctx.touch()                # 要約が無ければ何もしない
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


def test_set_summary_keeps_app():
    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    ctx.set_summary("メモを書いている。", app="notepad.exe")
    assert ctx.get_summary() == "メモを書いている。"
    assert ctx.get_app() == "notepad.exe"


def test_get_app_empty_when_summary_expired():
    t = {"now": 0.0}
    ctx = ScreenContext(summary_max_age_s=10.0, clock=lambda: t["now"])
    ctx.set_summary("x", app="chrome.exe")
    t["now"] = 100.0   # 期限切れ
    assert ctx.get_summary() is None
    assert ctx.get_app() == ""


def test_get_app_empty_by_default():
    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    ctx.set_summary("x")
    assert ctx.get_app() == ""
