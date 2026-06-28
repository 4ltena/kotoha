import threading

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


async def test_tick_normalizes_summary():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_describe_factory("画面に**99%**の負荷。詳細あり。蛇足。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is True
    assert ctx.get_summary() == "画面に99%の負荷。詳細あり。"   # 装飾除去＋2文クランプ


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


class _ClosableCapturer(_Capturer):
    def __init__(self):
        super().__init__()
        self.closed = False

    def close(self):
        self.closed = True


class _ThreadRecordingCapturer:
    def __init__(self):
        self.value = "IMG"
        self.calls = 0
        self.thread_ident = None

    def capture(self):
        self.calls += 1
        self.thread_ident = threading.get_ident()
        return self.value


async def test_capture_runs_off_the_event_loop_thread():
    ctx = _ctx()
    cap = _ThreadRecordingCapturer()
    p = ScreenPerceiver(
        capturer=cap, describe=_describe_factory("画面。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is True
    assert cap.calls == 1
    assert cap.thread_ident is not None
    assert cap.thread_ident != threading.get_ident()   # ループスレッドを塞がない


async def test_run_loops_until_stop():
    ctx = _ctx()
    cap = _Capturer()
    p = None

    async def fake_sleep(_):
        if cap.calls >= 3:
            p.stop()

    p = ScreenPerceiver(
        capturer=cap, describe=_describe_factory("画面。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5, sleep=fake_sleep,
    )
    await p.run()
    assert cap.calls == 3   # stop までキャプチャを繰り返した


async def test_run_closes_capturer_on_exit():
    ctx = _ctx()
    cap = _ClosableCapturer()
    p = None

    async def fake_sleep(_):
        p.stop()

    p = ScreenPerceiver(
        capturer=cap, describe=_describe_factory("画面。"),
        screen_ctx=ctx, normal_interval_s=1.0, realtime_interval_s=1.0, sleep=fake_sleep,
    )
    await p.run()
    assert cap.closed is True   # run() の finally でキャプチャ資源を解放


async def test_run_closes_capturer_on_cancel():
    import asyncio
    ctx = _ctx()
    cap = _ClosableCapturer()

    async def slow_sleep(_):
        await asyncio.sleep(3600)   # ここでキャンセルされる

    p = ScreenPerceiver(
        capturer=cap, describe=_describe_factory("画面。"),
        screen_ctx=ctx, normal_interval_s=1.0, realtime_interval_s=1.0, sleep=slow_sleep,
    )
    task = asyncio.ensure_future(p.run())
    for _ in range(5):   # tick を1回通してから sleep でブロックさせる
        await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert cap.closed is True   # キャンセルでも finally が走り解放される
