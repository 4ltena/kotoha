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
