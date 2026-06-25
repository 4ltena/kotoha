import numpy as np
from talk_ai.voice.vad import BargeInDetector


def _scripted(probs):
    it = iter(probs)
    return lambda frame: next(it)


def test_fires_once_when_sustained_speech_reaches_trigger():
    # trigger_ms=64 -> 2 consecutive speech frames
    probs = [0.1, 0.9, 0.9]
    det = BargeInDetector(_scripted(probs), threshold=0.5, trigger_ms=64)
    assert det.push(np.zeros(3 * 512, dtype=np.float32)) is True


def test_does_not_fire_on_silence():
    det = BargeInDetector(lambda f: 0.1, threshold=0.5, trigger_ms=64)
    assert det.push(np.zeros(4 * 512, dtype=np.float32)) is False


def test_resets_consecutive_count_on_gap():
    # speech, gap, speech -> never 2-in-a-row
    probs = [0.9, 0.1, 0.9, 0.1]
    det = BargeInDetector(_scripted(probs), threshold=0.5, trigger_ms=64)
    assert det.push(np.zeros(4 * 512, dtype=np.float32)) is False


def test_drain_returns_accumulated_speech_and_clears():
    probs = [0.9, 0.9, 0.9]
    det = BargeInDetector(_scripted(probs), threshold=0.5, trigger_ms=64)
    det.push(np.zeros(3 * 512, dtype=np.float32))
    pre = det.drain()
    assert pre.dtype == np.float32
    assert pre.shape == (3 * 512,)        # onset 以降の発話フレーム
    assert det.drain().shape == (0,)      # 2 回目は空


def test_reset_calls_reset_fn():
    resets = []
    det = BargeInDetector(lambda f: 0.1, reset_fn=lambda: resets.append(1))
    det.reset()
    assert resets == [1]
