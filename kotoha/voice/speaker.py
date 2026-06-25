import asyncio
import io
import wave
from typing import Optional, Tuple

import numpy as np


def _decode_wav(wav_bytes: bytes) -> Tuple[np.ndarray, int, int]:
    """WAV bytes -> (data(frames,channels) float32[-1,1], framerate, channels)。

    GPT-SoVITS の出力は 16-bit mono(sample rate はモデル依存, 通例 32000Hz)。
    16-bit 前提で int16 -> float32 へ正規化する。
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)
    if width != 2:
        raise ValueError(f"unsupported sample width: {width} (expected 16-bit)")
    i16 = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    data = i16.reshape(-1, channels)
    return data, rate, channels


class LocalSpeaker:
    """ローカルスピーカ再生 + barge-in。Orchestrator の Player 契約互換。

    再生は注入された sounddevice 互換バックエンドの OutputStream(callback 方式)で行う。
    callback はチャンクを index 進行で書き込み、末尾 or 中断で sd.CallbackStop を送出。
    finished_callback はイベントループへ marshalling して完了を通知する。
    """

    def __init__(self, *, sd=None, loop=None, on_amplitude=None):
        if sd is None:
            import sounddevice as sd  # 実機でのみ遅延 import(テストは fake を注入)
        self._sd = sd
        self._loop = loop
        self._on_amplitude = on_amplitude
        self._interrupted = False
        self._stream = None

    def is_playing(self) -> bool:
        return self._stream is not None

    def stop(self) -> None:
        self._interrupted = True
        stream = self._stream
        if stream is not None:
            self._stream = None
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    async def play_and_wait(self, wav_bytes: bytes) -> bool:
        loop = self._loop or asyncio.get_running_loop()
        self._interrupted = False
        data, rate, channels = _decode_wav(wav_bytes)
        total = len(data)
        idx = 0
        done = asyncio.Event()

        def callback(outdata, frames, time_info, status):
            nonlocal idx
            if self._interrupted:
                raise self._sd.CallbackStop
            chunk = data[idx : idx + frames]
            n = len(chunk)
            outdata[:n] = chunk
            idx += n
            if self._on_amplitude is not None and n > 0:
                level = float(np.sqrt(np.mean(np.square(chunk[:n]))))
                try:
                    self._on_amplitude(min(1.0, level))
                except Exception:
                    pass  # 口パク通知は best-effort(再生を妨げない)
            if n < frames:
                outdata[n:] = 0.0  # 最終(部分)バッファを 0 埋め
                raise self._sd.CallbackStop

        def finished_callback():
            loop.call_soon_threadsafe(done.set)

        stream = self._sd.OutputStream(
            samplerate=rate,
            channels=channels,
            dtype="float32",
            callback=callback,
            finished_callback=finished_callback,
        )
        self._stream = stream
        stream.start()
        try:
            await done.wait()
        finally:
            if self._stream is stream:  # stop() が先に閉じていなければ後始末
                self._stream = None
                try:
                    stream.close()
                except Exception:
                    pass
        return not self._interrupted
