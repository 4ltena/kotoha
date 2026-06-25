import numpy as np
from kotoha.voice.audio_utils import resample_linear, pcm_s16le_to_float32_mono_16k


def test_resample_linear_decimates_48k_to_16k():
    x = np.array([0, 1, 2, 3, 4, 5], dtype=np.float32)
    out = resample_linear(x, 48000, 16000)
    assert out.dtype == np.float32
    assert out.shape == (2,)            # round(6 * 16000/48000) = 2
    np.testing.assert_allclose(out, [0.0, 5.0])


def test_resample_same_rate_is_passthrough():
    x = np.array([0.1, 0.2], dtype=np.float32)
    np.testing.assert_allclose(resample_linear(x, 16000, 16000), x)


def test_pcm_stereo_48k_to_mono_16k_float32():
    # 6 stereo pairs, all value 16384 -> mono 0.5, 48k->16k -> 2 samples
    i16 = np.full(12, 16384, dtype=np.int16)
    out = pcm_s16le_to_float32_mono_16k(i16.tobytes())
    assert out.dtype == np.float32
    assert out.shape == (2,)
    np.testing.assert_allclose(out, [0.5, 0.5], atol=1e-4)


def test_pcm_empty_returns_empty():
    out = pcm_s16le_to_float32_mono_16k(b"")
    assert out.dtype == np.float32
    assert out.shape == (0,)
