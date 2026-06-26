import asyncio

import numpy as np

from kotoha.config import Config
from kotoha.remote.server import RemoteAudioServer


async def test_feed_decodes_int16_to_float32():
    srv = RemoteAudioServer(config=Config(), loop=asyncio.get_event_loop())
    got = []
    srv.set_on_audio(lambda uid, pcm: got.append((uid, pcm)))

    data = np.array([0, 16384, -16384], dtype=np.int16).tobytes()
    srv._feed(data)

    assert len(got) == 1
    uid, pcm = got[0]
    assert uid == 0
    assert pcm.dtype == np.float32
    assert abs(pcm[1] - 0.5) < 0.01      # 16384/32768
    assert abs(pcm[2] + 0.5) < 0.01


async def test_feed_no_callback_is_safe():
    srv = RemoteAudioServer(config=Config(), loop=asyncio.get_event_loop())
    srv._feed(np.array([1, 2], dtype=np.int16).tobytes())   # on_audio 未設定でも落ちない


class _Req:
    def __init__(self, t, origin=None, host="pc:5108"):
        self.query = {"t": t}
        self.headers = {"Origin": origin} if origin else {}
        self.host = host


async def test_authorized_checks_token_and_origin():
    srv = RemoteAudioServer(config=Config(), loop=asyncio.get_event_loop(), token="secret")
    assert srv._authorized(_Req("secret")) is True
    assert srv._authorized(_Req("wrong")) is False
    assert srv._authorized(_Req("secret", origin="https://pc:5108")) is True
    assert srv._authorized(_Req("secret", origin="https://evil.example")) is False

