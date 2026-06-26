"""リモート端末へ合成音声を送って鳴らす player。orchestrator の player 契約を満たす。

play_and_wait は WAV を送り、その再生時間ぶん待つ(または barge-in の stop で中断)。
is_playing/stop は割り込み制御に使う。client からの再生完了 ack は使わず、WAV の
時間長で近似する(client 側はキューで順序再生する前提)。
"""

import asyncio
import io
import logging
import wave

logger = logging.getLogger(__name__)


def wav_duration(wav_bytes: bytes) -> float:
    """自己記述 WAV の再生時間(秒)。解析不能なら 0.0。"""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate() or 1
            return w.getnframes() / float(rate)
    except Exception:
        return 0.0


class RemotePlayer:
    def __init__(self, *, loop, send_audio, send_control):
        self._loop = loop
        self._send_audio = send_audio      # async (wav: bytes) -> None
        self._send_control = send_control  # async (msg: dict) -> None
        self._playing = False
        self._stop = asyncio.Event()

    def is_playing(self) -> bool:
        return self._playing

    def stop(self) -> None:
        # barge-in(ループスレッド)から呼ばれる。待機を解除し、client へ停止通知。
        self._stop.set()
        self._loop.create_task(self._send_control({"type": "stop"}))

    async def play_and_wait(self, wav: bytes) -> bool:
        self._playing = True
        self._stop.clear()
        try:
            await self._send_audio(wav)
            dur = wav_duration(wav)
            if dur > 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=dur)
                except asyncio.TimeoutError:
                    pass
            return True
        finally:
            self._playing = False
