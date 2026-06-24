import numpy as np
import pytest
from talk_ai.voice.vad import VadSegmenter


def _scripted(probs):
    it = iter(probs)
    return lambda frame: next(it)


def test_segmenter_emits_one_utterance_after_silence():
    # 3 speech frames then 2 silence frames; silence_ms=64ms -> 2 frames (512/16k=32ms)
    probs = [0.9, 0.9, 0.9, 0.1, 0.1]
    seg = VadSegmenter(_scripted(probs), threshold=0.5, silence_ms=64)
    out = seg.push(np.zeros(5 * 512, dtype=np.float32))
    assert len(out) == 1
    assert out[0].shape == (5 * 512,)          # speech + trailing silence frames
    assert out[0].dtype == np.float32


def test_segmenter_no_emit_while_still_speaking():
    probs = [0.9, 0.9, 0.9]
    seg = VadSegmenter(_scripted(probs), threshold=0.5, silence_ms=64)
    assert seg.push(np.zeros(3 * 512, dtype=np.float32)) == []


def test_segmenter_drops_partial_trailing_frame():
    seg = VadSegmenter(lambda f: 0.0, threshold=0.5, silence_ms=64)
    # 700 samples -> 1 full 512 frame processed, 188 buffered (dropped from this call)
    out = seg.push(np.zeros(700, dtype=np.float32))
    assert out == []


def test_segmenter_calls_reset_fn_on_utterance_finalization():
    resets = []
    probs = [0.9, 0.9, 0.1, 0.1]
    seg = VadSegmenter(
        _scripted(probs), threshold=0.5, silence_ms=64,
        reset_fn=lambda: resets.append(1),
    )
    seg.push(np.zeros(4 * 512, dtype=np.float32))
    assert resets == [1]            # 区間確定でストリーム切替 -> VAD 状態リセット


# --- integration: 実 silero-vad モデルでテンソル形状/値域/区間検出を検証(点15) ---
@pytest.mark.integration
def test_real_silero_prob_shape_and_range():
    pytest.importorskip("torch")
    pytest.importorskip("silero_vad")
    from talk_ai.voice.vad import SileroVad

    vad = SileroVad()
    p = vad.prob(np.zeros(512, dtype=np.float32))
    assert isinstance(p, float) and 0.0 <= p <= 1.0
    vad.reset()


@pytest.mark.integration
def test_real_silero_segmenter_no_utterance_on_silence():
    pytest.importorskip("torch")
    pytest.importorskip("silero_vad")
    from talk_ai.voice.vad import SileroVad

    vad = SileroVad()
    seg = VadSegmenter(vad.prob, reset_fn=vad.reset, silence_ms=200)
    out = seg.push(np.zeros(30 * 512, dtype=np.float32))   # 無音 -> 区間は出ない
    assert out == []
