from typing import Callable, Optional

import numpy as np

from kotoha.config import SAMPLE_RATE_HZ, VAD_WINDOW_SAMPLES


class MicCapture:
    """ローカルマイクから 16kHz mono float32 を取り込み、512 サンプルのフレームを
    `on_audio(user_id, frame)` へ転送する。

    sounddevice の InputStream コールバックは PortAudio スレッド上で実行されるため、
    `on_audio` は非 async スレッドから呼ばれる前提(=> orch.feed_audio を直接駆動できる)。
    テストでは `sd` に fake モジュールを注入し、ハードウェア不要で検証する。
    """

    def __init__(
        self,
        on_audio: Callable[[int, np.ndarray], None],
        *,
        user_id: int = 0,
        samplerate: int = SAMPLE_RATE_HZ,
        blocksize: int = VAD_WINDOW_SAMPLES,
        device=None,
        sd=None,
    ) -> None:
        if sd is None:
            import sounddevice as sd  # 遅延 import(テストは fake を注入)
        self._sd = sd
        self._on_audio = on_audio
        self._user_id = user_id
        self._samplerate = samplerate
        self._blocksize = blocksize
        self._device = device
        self._stream = None

    def _cb(self, indata, frames, time, status) -> None:
        # indata: shape (frames, 1) float32 -> (frames,) float32
        frame = np.asarray(indata, dtype=np.float32).reshape(-1)
        self._on_audio(self._user_id, frame)

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = self._sd.InputStream(
            samplerate=self._samplerate,
            channels=1,
            dtype="float32",
            blocksize=self._blocksize,
            device=self._device,
            callback=self._cb,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is None:
            return
        stream, self._stream = self._stream, None
        stream.stop()
        stream.close()

    def close(self) -> None:
        self.stop()

    def __enter__(self) -> "MicCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
