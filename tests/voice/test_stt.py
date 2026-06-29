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


def test_transcribe_drops_high_no_speech_prob_segment():
    class _S:
        def __init__(self, text, nsp):
            self.text = text
            self.no_speech_prob = nsp

    class _M:
        def transcribe(self, audio, **kwargs):
            return iter([_S("(雑音)", 0.95), _S("こんにちは", 0.05)]), object()

    t = Transcriber(_M(), no_speech_threshold=0.6)
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == "こんにちは"


def test_transcribe_blocks_known_hallucination_phrase():
    class _M:
        def transcribe(self, audio, **kwargs):
            return iter([_Seg("ご視聴ありがとうございました")]), object()

    t = Transcriber(_M(), hallucination_blocklist=("ご視聴ありがとうございました",))
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == ""


@pytest.mark.integration
def test_real_whisper_transcribes_silence_to_str():
    pytest.importorskip("faster_whisper")
    from kotoha.voice.stt import build_whisper

    model = build_whisper("tiny", device="cpu", compute_type="int8")
    out = Transcriber(model).transcribe(np.zeros(16000, dtype=np.float32))
    assert isinstance(out, str)
