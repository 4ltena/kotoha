import asyncio
import io
import wave

import numpy as np
import pytest

from kotoha.voice.speaker import LocalSpeaker


def _make_wav(samples_i16: np.ndarray, *, rate: int = 32000, channels: int = 1) -> bytes:
    """stdlib wave で最小の in-memory 16-bit WAV を構築。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples_i16.astype("<i2").tobytes())
    return buf.getvalue()


class _FakeStream:
    """sd.OutputStream 互換の fake。start() で callback を駆動して再生を模擬する。"""

    def __init__(self, fake, **kwargs):
        self._fake = fake
        self.kwargs = kwargs
        self.samplerate = kwargs.get("samplerate")
        self.channels = kwargs.get("channels", 1)
        self.callback = kwargs.get("callback")
        self.finished_callback = kwargs.get("finished_callback")
        self.frames_written: list[np.ndarray] = []
        self.started = False
        self.aborted = False
        self.closed = False

    def start(self):
        self.started = True
        if not self._fake.auto_finish:
            # 手動モード: stream をアクティブにしたまま戻る(barge-in テスト用)
            return
        blocksize = 512
        while True:
            outdata = np.zeros((blocksize, self.channels), dtype=np.float32)
            try:
                self.callback(outdata, blocksize, None, None)
            except self._fake.CallbackStop:
                self.frames_written.append(outdata)  # 最終(部分)バッファも収集
                break
            self.frames_written.append(outdata)
        if self.finished_callback is not None:
            self.finished_callback()  # PortAudio 終了通知を模擬

    def abort(self):
        self.aborted = True
        if self.finished_callback is not None:
            self.finished_callback()  # 実 sounddevice は abort で finished_callback を発火

    def close(self):
        self.closed = True

    def stop(self):
        pass


class FakeSd:
    """sounddevice 互換の最小 fake。"""

    class CallbackStop(Exception):
        pass

    def __init__(self, auto_finish: bool = True):
        self.auto_finish = auto_finish
        self.streams: list[_FakeStream] = []

    def OutputStream(self, **kwargs):
        s = _FakeStream(self, **kwargs)
        self.streams.append(s)
        return s


async def test_play_and_wait_true_on_natural_finish_and_decodes_wav():
    rate = 32000
    i16 = (np.linspace(-10000, 10000, 1000)).astype(np.int16)
    wav = _make_wav(i16, rate=rate, channels=1)

    fake = FakeSd(auto_finish=True)
    spk = LocalSpeaker(sd=fake)
    ok = await spk.play_and_wait(wav)

    assert ok is True
    assert len(fake.streams) == 1
    stream = fake.streams[0]
    # WAV ヘッダ通りに OutputStream を構築している
    assert stream.samplerate == rate
    assert stream.channels == 1
    # WAV フレームを正しく読み出し callback へ流している
    played = np.concatenate(stream.frames_written, axis=0)[: len(i16)]
    expected = (i16.astype(np.float32) / 32768.0).reshape(-1, 1)
    assert np.allclose(played, expected, atol=1e-4)
    assert spk.is_playing() is False  # 終了後はクリア


async def test_stop_during_playback_returns_false():
    wav = _make_wav(np.zeros(2000, dtype=np.int16), rate=32000, channels=1)
    fake = FakeSd(auto_finish=False)  # start() では終わらせない
    spk = LocalSpeaker(sd=fake)

    task = asyncio.create_task(spk.play_and_wait(wav))
    await asyncio.sleep(0)            # play_and_wait を start()→await まで進める
    assert spk.is_playing() is True

    spk.stop()                        # barge-in
    result = await task
    assert result is False
    assert fake.streams[0].aborted is True


async def test_is_playing_reflects_active_stream():
    wav = _make_wav(np.zeros(2000, dtype=np.int16), rate=32000, channels=1)
    fake = FakeSd(auto_finish=False)
    spk = LocalSpeaker(sd=fake)

    assert spk.is_playing() is False
    task = asyncio.create_task(spk.play_and_wait(wav))
    await asyncio.sleep(0)
    assert spk.is_playing() is True
    spk.stop()
    await task
    assert spk.is_playing() is False


async def test_on_amplitude_reports_levels_for_nonsilent_audio():
    rate = 32000
    i16 = (np.ones(1024) * 16384).astype(np.int16)   # 一定振幅 0.5
    wav = _make_wav(i16, rate=rate, channels=1)

    levels = []
    fake = FakeSd(auto_finish=True)
    spk = LocalSpeaker(sd=fake, on_amplitude=lambda v: levels.append(v))
    await spk.play_and_wait(wav)

    assert levels                              # 振幅が通知された
    assert all(0.0 <= v <= 1.0 for v in levels)
    assert max(levels) > 0.0                    # 無音ではない


async def test_on_amplitude_zero_for_silence():
    wav = _make_wav(np.zeros(1024, dtype=np.int16), rate=32000, channels=1)
    levels = []
    fake = FakeSd(auto_finish=True)
    spk = LocalSpeaker(sd=fake, on_amplitude=lambda v: levels.append(v))
    await spk.play_and_wait(wav)

    assert levels
    assert max(levels) == 0.0


@pytest.mark.integration
def test_plays_short_tone_on_real_hardware():
    pytest.importorskip("sounddevice")
    rate = 32000
    t = np.linspace(0, 0.2, int(rate * 0.2), endpoint=False)
    tone = (0.2 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    wav = _make_wav(tone, rate=rate, channels=1)

    spk = LocalSpeaker()  # 実 sounddevice を使用
    ok = asyncio.run(spk.play_and_wait(wav))
    assert ok is True
