import numpy as np
import pytest

from kotoha.config import SAMPLE_RATE_HZ, VAD_WINDOW_SAMPLES
from kotoha.voice.mic import MicCapture


class FakeStream:
    """sounddevice.InputStream のスタブ。start/stop/close を記録する。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callback = kwargs.get("callback")
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeSd:
    """sounddevice モジュールのスタブ。生成した InputStream を保持する。"""

    def __init__(self):
        self.last_stream = None

    def InputStream(self, **kwargs):
        self.last_stream = FakeStream(**kwargs)
        return self.last_stream


def test_start_opens_inputstream_with_expected_params():
    sd = FakeSd()
    mic = MicCapture(lambda uid, frame: None, sd=sd)
    mic.start()

    s = sd.last_stream
    assert s is not None
    assert s.kwargs["samplerate"] == SAMPLE_RATE_HZ
    assert s.kwargs["channels"] == 1
    assert s.kwargs["dtype"] == "float32"
    assert s.kwargs["blocksize"] == VAD_WINDOW_SAMPLES
    assert s.kwargs["device"] is None
    assert s.started is True


def test_callback_flattens_and_forwards_frame():
    sd = FakeSd()
    received = []
    mic = MicCapture(
        lambda uid, frame: received.append((uid, frame)),
        user_id=7,
        sd=sd,
    )
    mic.start()

    indata = np.full((VAD_WINDOW_SAMPLES, 1), 0.25, dtype=np.float32)
    sd.last_stream.callback(indata, VAD_WINDOW_SAMPLES, None, None)

    assert len(received) == 1
    uid, frame = received[0]
    assert uid == 7
    assert frame.shape == (VAD_WINDOW_SAMPLES,)
    assert frame.dtype == np.float32
    assert np.allclose(frame, 0.25)


def test_stop_calls_stream_stop_and_close():
    sd = FakeSd()
    mic = MicCapture(lambda uid, frame: None, sd=sd)
    mic.start()
    mic.stop()

    s = sd.last_stream
    assert s.stopped is True
    assert s.closed is True


def test_context_manager_starts_and_stops():
    sd = FakeSd()
    with MicCapture(lambda uid, frame: None, sd=sd) as mic:
        assert isinstance(mic, MicCapture)
        s = sd.last_stream
        assert s.started is True
        assert s.stopped is False
    assert s.stopped is True
    assert s.closed is True


def test_custom_device_and_samplerate_passed_through():
    sd = FakeSd()
    mic = MicCapture(
        lambda uid, frame: None,
        samplerate=8000,
        blocksize=256,
        device="hw:1",
        sd=sd,
    )
    mic.start()

    s = sd.last_stream
    assert s.kwargs["samplerate"] == 8000
    assert s.kwargs["blocksize"] == 256
    assert s.kwargs["device"] == "hw:1"


@pytest.mark.integration
def test_real_inputstream_smoke():
    pytest.importorskip("sounddevice")
    import sounddevice as sd  # noqa: F811

    received = []
    mic = MicCapture(lambda uid, frame: received.append(frame), sd=sd)
    try:
        mic.start()
    except Exception as e:  # 無音声デバイス環境ではスキップ
        pytest.skip(f"no audio input device: {e}")
    finally:
        mic.stop()
