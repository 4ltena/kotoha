from kotoha.config import Config
from kotoha.screen.state import ScreenContext
from kotoha.screen.detector import GameModeLoop


def _loop(foreground, **overrides):
    ctx = ScreenContext(clock=lambda: 0.0)
    cfg = Config(**overrides)
    loop = GameModeLoop(screen_ctx=ctx, config=cfg, get_foreground=lambda: foreground)
    return ctx, loop


async def test_normal_when_no_game():
    ctx, loop = _loop({"fullscreen": False, "process": "notepad.exe"})
    await loop.tick()
    assert ctx.mode == "normal"


async def test_powersave_on_fullscreen_default():
    ctx, loop = _loop({"fullscreen": True, "process": "game.exe"})
    await loop.tick()
    assert ctx.mode == "game_powersave"


async def test_realtime_when_configured():
    ctx, loop = _loop({"fullscreen": True, "process": "game.exe"}, screen_game_mode="realtime")
    await loop.tick()
    assert ctx.mode == "game_realtime"


async def test_process_list_triggers_without_fullscreen():
    ctx, loop = _loop(
        {"fullscreen": False, "process": "EldenRing.exe"},
        screen_game_detect_fullscreen=False,
        screen_game_process_names=("eldenring",),
    )
    await loop.tick()
    assert ctx.mode == "game_powersave"


async def test_run_loops_until_stop_and_applies_mode():
    ctx = ScreenContext(clock=lambda: 0.0)
    calls = {"n": 0}
    loop = None

    async def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 2:
            loop.stop()

    loop = GameModeLoop(
        screen_ctx=ctx, config=Config(),
        get_foreground=lambda: {"fullscreen": True, "process": "g.exe"},
        sleep=fake_sleep,
    )
    await loop.run()
    assert ctx.mode == "game_powersave"   # tick がモードを反映した
    assert calls["n"] == 2                 # stop までループした


def test_get_foreground_info_none_off_windows(monkeypatch):
    import kotoha.screen.detector as d
    monkeypatch.setattr(d.sys, "platform", "linux")
    assert d.get_foreground_info() is None   # 非Windowsでは静かに None
