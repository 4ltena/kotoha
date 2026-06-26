import asyncio
import io
import wave

from kotoha.remote.player import wav_duration, RemotePlayer


def _wav(seconds, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_wav_duration():
    assert abs(wav_duration(_wav(0.5)) - 0.5) < 0.01
    assert wav_duration(b"not a wav") == 0.0


async def test_play_and_wait_sends_and_clears_playing():
    sent = []

    async def send_audio(w):
        sent.append(w)

    async def send_control(m):
        pass

    p = RemotePlayer(
        loop=asyncio.get_event_loop(), send_audio=send_audio, send_control=send_control
    )
    wav = _wav(0.05)
    assert not p.is_playing()
    await p.play_and_wait(wav)
    assert sent == [wav]
    assert not p.is_playing()


async def test_stop_interrupts_play_and_notifies_client():
    ctrl = []

    async def send_audio(w):
        pass

    async def send_control(m):
        ctrl.append(m)

    p = RemotePlayer(
        loop=asyncio.get_event_loop(), send_audio=send_audio, send_control=send_control
    )
    task = asyncio.create_task(p.play_and_wait(_wav(5.0)))   # 長い音声
    await asyncio.sleep(0.05)
    assert p.is_playing()
    p.stop()
    await asyncio.wait_for(task, timeout=1.0)   # stop で早期終了
    assert not p.is_playing()
    await asyncio.sleep(0.01)                    # stop が投げた送信タスクの実行を待つ
    assert {"type": "stop"} in ctrl
