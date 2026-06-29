"""背景の画面知覚ループ。一定間隔でキャプチャし、VLM で要約して ScreenContext へ書く。

best-effort。capture / describe のどの失敗でも要約を更新しないだけで、例外を上へ投げない。
省力型ゲームモード中はキャプチャを行わない。
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from kotoha.screen.sanitize import normalize_summary

logger = logging.getLogger(__name__)


class ScreenPerceiver:
    def __init__(
        self,
        *,
        capturer,
        describe,
        screen_ctx,
        normal_interval_s: float,
        realtime_interval_s: float,
        poll_s: float = 2.0,
        sleep=asyncio.sleep,
        stats=None,
    ):
        self._capturer = capturer
        self._describe = describe          # async (image_b64) -> str
        self._screen_ctx = screen_ctx
        self._normal_interval = normal_interval_s
        self._realtime_interval = realtime_interval_s
        self._poll_s = poll_s
        self._sleep = sleep
        self._stop = False
        self._last_capture_b64 = None   # 直近に要約したフレーム。同一なら再要約しない
        self._stats = stats
        # キャプチャ(mss/dxcam)はブロッキングで、会話ループと同じスレッドで実行すると
        # barge-in・TTS・再生を止める。単一ワーカーへ逃がす。max_workers=1 で
        # スレッド固有のキャプチャ資源(GDI/DXGI)を常に同じスレッドに固定する。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screencap")

    def _interval(self) -> float:
        mode = self._screen_ctx.mode
        if mode == "game_realtime":
            return self._realtime_interval
        if mode == "game_powersave":
            return self._poll_s
        return self._normal_interval

    async def tick(self) -> bool:
        """1サイクル。要約を更新できたら True。"""
        mode = self._screen_ctx.mode
        if self._stats is not None:
            self._stats.set_mode(mode)
        if mode == "game_powersave":
            return False
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            image_b64 = await loop.run_in_executor(self._executor, self._capturer.capture)
        except Exception:
            logger.warning("screen capture raised", exc_info=True)
            if self._stats is not None:
                self._stats.record_failure("capture")
            return False
        if not image_b64:
            return False
        if self._stats is not None:
            self._stats.record_capture((loop.time() - t0) * 1000)
        if image_b64 == self._last_capture_b64:
            # 画面が変わっていない: 重い VLM を呼ばず、要約の鮮度だけ更新する。
            self._screen_ctx.touch()
            if self._stats is not None:
                self._stats.record_skip()
            return False
        t1 = loop.time()
        try:
            summary = await self._describe(image_b64)
        except Exception:
            logger.warning("VLM describe failed", exc_info=True)
            if self._stats is not None:
                self._stats.record_failure("vlm")
            return False
        if self._stats is not None:
            self._stats.record_describe((loop.time() - t1) * 1000)
        summary = normalize_summary(summary)   # 装飾除去・最大2文へ均す
        if summary:
            self._last_capture_b64 = image_b64
            self._screen_ctx.set_summary(summary)
            if self._stats is not None:
                self._stats.record_summary_update()
            return True
        return False

    async def run(self) -> None:
        try:
            while not self._stop:
                await self.tick()
                await self._sleep(self._interval())
        finally:
            # 停止・キャンセルのいずれでもキャプチャ資源を解放し、ワーカーを畳む。
            # close はキャプチャを生成したワーカースレッドで実行する(スレッド固定を保つ)。
            close = getattr(self._capturer, "close", None)
            if callable(close):
                try:
                    self._executor.submit(close)
                except RuntimeError:
                    pass   # 既に shutdown 済み
            self._executor.shutdown(wait=True)

    def stop(self) -> None:
        self._stop = True
