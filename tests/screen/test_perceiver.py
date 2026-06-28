import pytest

from kotoha.screen.state import ScreenContext
from kotoha.screen.perceiver import ScreenPerceiver


class _Capturer:
    def __init__(self, value="IMGB64"): self.value = value; self.calls = 0
    def capture(self):
        self.calls += 1
        return self.value


def _describe_factory(text):
    async def _describe(image_b64):
        return text
    return _describe


def _ctx():
    return ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)


async def test_tick_updates_summary():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_describe_factory("画面にエディタ。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is True
    assert ctx.get_summary() == "画面にエディタ。"


async def test_powersave_skips_capture():
    ctx = _ctx()
    ctx.set_mode("game_powersave")
    cap = _Capturer()
    p = ScreenPerceiver(
        capturer=cap, describe=_describe_factory("x"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is False
    assert cap.calls == 0
    assert ctx.get_summary() is None


async def test_capture_none_does_not_crash():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(value=None), describe=_describe_factory("x"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is False
    assert ctx.get_summary() is None


async def test_describe_exception_is_swallowed():
    ctx = _ctx()
    async def _boom(image_b64): raise RuntimeError("vlm down")
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_boom,
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is False   # 会話を止めない


def test_interval_by_mode():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_describe_factory("x"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5, poll_s=2.0,
    )
    assert p._interval() == 4.0
    ctx.set_mode("game_realtime"); assert p._interval() == 0.5
    ctx.set_mode("game_powersave"); assert p._interval() == 2.0
