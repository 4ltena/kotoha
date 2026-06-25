import numpy as np
import pytest
from kotoha.voice.stt import Transcriber


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeWhisper:
    def __init__(self):
        self.last_kwargs = None

    def transcribe(self, audio, **kwargs):
        self.last_kwargs = kwargs
        assert audio.dtype == np.float32
        return iter([_Seg("こんにちは"), _Seg("世界")]), object()


def test_transcribe_joins_segments_and_strips():
    fake = _FakeWhisper()
    t = Transcriber(fake, language="ja")
    out = t.transcribe(np.zeros(16000, dtype=np.float32))
    assert out == "こんにちは世界"
    assert fake.last_kwargs["language"] == "ja"
    assert fake.last_kwargs["beam_size"] == 5


def test_transcribe_empty_segments_returns_empty_string():
    class _Empty:
        def transcribe(self, audio, **kwargs):
            return iter([]), object()

    assert Transcriber(_Empty()).transcribe(np.zeros(16000, dtype=np.float32)) == ""


@pytest.mark.integration
def test_real_whisper_transcribes_silence_to_str():
    pytest.importorskip("faster_whisper")
    from kotoha.voice.stt import build_whisper

    model = build_whisper("tiny", device="cpu", compute_type="int8")
    out = Transcriber(model).transcribe(np.zeros(16000, dtype=np.float32))
    assert isinstance(out, str)
