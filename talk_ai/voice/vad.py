from typing import Callable, Optional

import numpy as np


def _frames_for_ms(ms: int, window: int, sample_rate: int) -> int:
    frame_ms = window / sample_rate * 1000.0
    return max(1, int(ms / frame_ms))


class SileroVad:
    """silero-vad ラッパ。frame は正確に `window` samples の float32(shape (512,))。

    ステートフル(内部 LSTM)。1 インスタンス = 1 連続ストリーム専用。
    独立ストリーム(別話者・別用途・新発話)を処理する前に reset() を呼ぶ。
    """

    def __init__(self, sample_rate: int = 16000):
        from silero_vad import load_silero_vad
        import torch

        self._torch = torch
        self._model = load_silero_vad()
        self._sr = sample_rate

    def prob(self, frame: np.ndarray) -> float:
        # frame: np.ndarray shape (512,) -> torch.float32 tensor
        t = self._torch.as_tensor(frame, dtype=self._torch.float32)
        return self._model(t, self._sr).item()   # tensor -> Python float in [0,1]

    def reset(self) -> None:
        self._model.reset_states()


class VadSegmenter:
    """16kHz float32 を流し込み、無音で区切れた発話区間を返す。

    区間確定時(=ストリーム切替)に reset_fn() を呼び、背後の VAD 状態を初期化する。
    """

    def __init__(
        self,
        prob_fn: Callable[[np.ndarray], float],
        *,
        threshold: float = 0.5,
        silence_ms: int = 400,
        sample_rate: int = 16000,
        window: int = 512,
        reset_fn: Optional[Callable[[], None]] = None,
    ):
        self._prob_fn = prob_fn
        self._reset_fn = reset_fn
        self._threshold = threshold
        self._window = window
        self._silence_frames = _frames_for_ms(silence_ms, window, sample_rate)
        self._tail = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._silence_count = 0
        self._buf: list[np.ndarray] = []

    def push(self, audio: np.ndarray) -> list[np.ndarray]:
        self._tail = np.concatenate([self._tail, np.asarray(audio, dtype=np.float32)])
        out: list[np.ndarray] = []
        while len(self._tail) >= self._window:
            frame = self._tail[: self._window]
            self._tail = self._tail[self._window :]
            if self._prob_fn(frame) >= self._threshold:
                if not self._in_speech:
                    self._in_speech = True
                    self._buf = []
                self._buf.append(frame)
                self._silence_count = 0
            elif self._in_speech:
                self._buf.append(frame)
                self._silence_count += 1
                if self._silence_count >= self._silence_frames:
                    out.append(np.concatenate(self._buf))
                    self._in_speech = False
                    self._silence_count = 0
                    self._buf = []
                    if self._reset_fn is not None:
                        self._reset_fn()   # 区間確定 = ストリーム切替 -> silero 状態リセット
        return out

    def reset(self) -> None:
        self._tail = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._silence_count = 0
        self._buf = []
        if self._reset_fn is not None:
            self._reset_fn()
