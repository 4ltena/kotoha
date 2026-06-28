"""背景の画面知覚ループ。一定間隔でキャプチャし、VLM で要約して ScreenContext へ書く。

best-effort。capture / describe のどの失敗でも要約を更新しないだけで、例外を上へ投げない。
省力型ゲームモード中はキャプチャを行わない。
"""

import asyncio
import logging

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
    ):
        self._capturer = capturer
        self._describe = describe          # async (image_b64) -> str
        self._screen_ctx = screen_ctx
        self._normal_interval = normal_interval_s
        self._realtime_interval = realtime_interval_s
        self._poll_s = poll_s
        self._sleep = sleep
        self._stop = False

    def _interval(self) -> float:
        mode = self._screen_ctx.mode
        if mode == "game_realtime":
            return self._realtime_interval
        if mode == "game_powersave":
            return self._poll_s
        return self._normal_interval

    async def tick(self) -> bool:
        """1サイクル。要約を更新できたら True。"""
        if self._screen_ctx.mode == "game_powersave":
            return False
        try:
            image_b64 = self._capturer.capture()
        except Exception:
            logger.warning("screen capture raised", exc_info=True)
            return False
        if not image_b64:
            return False
        try:
            summary = await self._describe(image_b64)
        except Exception:
            logger.warning("VLM describe failed", exc_info=True)
            return False
        if summary:
            self._screen_ctx.set_summary(summary)
            return True
        return False

    async def run(self) -> None:
        while not self._stop:
            await self.tick()
            await self._sleep(self._interval())

    def stop(self) -> None:
        self._stop = True
