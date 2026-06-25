import asyncio
import numpy as np
from kotoha.orchestrator import Orchestrator
from kotoha.llm import persona


class _FakeTranscriber:
    def __init__(self, text):
        self._text = text

    def transcribe(self, audio):
        return self._text


def _slow_llm_factory(reached: asyncio.Event):
    async def _llm(messages, *, model):
        yield "こんにち"
        yield "は。"
        reached.set()          # 1文目を出し切った合図
        await asyncio.sleep(10) # ここで詰まらせる
        yield "もっと"
    return _llm


async def _fake_tts(text):
    return ("WAV:" + text).encode()


class _BargePlayer:
    def __init__(self):
        self.played = []
        self.stops = 0
        self._playing = False
        self.first_play = asyncio.Event()

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return False

    def stop(self):
        self.stops += 1
        self._playing = False

    async def play_and_wait(self, wav):
        self.played.append(wav)
        self._playing = True
        self.first_play.set()
        return True


class _CountingVad:
    """ステートフル VAD の擬似。reset 回数を記録する。"""
    def __init__(self, probs):
        self._it = iter(probs)
        self.resets = 0

    def prob(self, frame):
        try:
            return next(self._it)
        except StopIteration:
            return 0.0

    def reset(self):
        self.resets += 1


async def test_request_bargein_cancels_and_saves_partial():
    reached = asyncio.Event()
    player = _BargePlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("ねえ"),
        llm_stream=_slow_llm_factory(reached),
        tts=_fake_tts, player=player, model="m",
        vad_factory=lambda: _CountingVad([]), persona=persona,
    )
    task = asyncio.create_task(orch.handle_utterance(1, np.zeros(512, dtype=np.float32)))
    # sleep ベースをやめ、同期点で「1文目再生済み・LLM が詰まった」状態を確定(点21)
    await asyncio.wait_for(player.first_play.wait(), timeout=2.0)
    await asyncio.wait_for(reached.wait(), timeout=2.0)
    orch.request_bargein()
    await asyncio.sleep(0)

    assert player.stops == 1
    assert player.played == [b"WAV:" + "こんにちは。".encode()]
    assert list(orch.history)[-1] == {"role": "assistant", "content": "こんにちは。"}
    await task    # CancelledError は handle_utterance が握り潰す


async def test_route_audio_triggers_bargein_while_playing():
    player = _BargePlayer()
    player._playing = True
    orch = Orchestrator(
        transcriber=_FakeTranscriber("x"),
        llm_stream=_slow_llm_factory(asyncio.Event()),
        tts=_fake_tts, player=player, model="m",
        vad_factory=lambda: _CountingVad([0.9] * 10), persona=persona,
    )
    orch._loop = asyncio.get_running_loop()
    fired = []
    orch.request_bargein = lambda user_id=None: fired.append(user_id)
    orch._route_audio(1, np.zeros(8 * 512, dtype=np.float32))   # trigger=7frames
    await asyncio.sleep(0)
    assert fired == [1]


async def test_route_audio_segments_utterance_while_idle():
    player = _BargePlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("x"),
        llm_stream=_slow_llm_factory(asyncio.Event()),
        tts=_fake_tts, player=player, model="m",
        vad_factory=lambda: _CountingVad([0.9, 0.9, 0.9, 0.1, 0.1]),
        vad_silence_ms=64, persona=persona,
    )
    orch._loop = asyncio.get_running_loop()
    seen = []

    async def _rec(uid, audio):
        seen.append((uid, len(audio)))

    orch.handle_utterance = _rec
    orch._route_audio(7, np.zeros(5 * 512, dtype=np.float32))
    await asyncio.sleep(0)   # _spawn_turn を走らせる
    await asyncio.sleep(0)   # handle_utterance(_rec) を走らせる
    assert seen == [(7, 5 * 512)]
    assert orch._last_speaker == 7


async def test_vad_factory_creates_independent_streams_per_user():
    created = []

    def factory():
        v = _CountingVad([0.0] * 50)
        created.append(v)
        return v

    player = _BargePlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("x"),
        llm_stream=_slow_llm_factory(asyncio.Event()),
        tts=_fake_tts, player=player, model="m",
        vad_factory=factory, persona=persona,
    )
    orch._loop = asyncio.get_running_loop()
    orch._route_audio(1, np.zeros(512, dtype=np.float32))   # user1 のセグメンタ
    orch._route_audio(2, np.zeros(512, dtype=np.float32))   # user2 のセグメンタ
    assert len(created) == 2     # 話者ごとに独立した silero ストリーム


async def test_request_bargein_resets_vad_streams():
    vad = _CountingVad([0.9] * 20)
    player = _BargePlayer()
    player._playing = True
    orch = Orchestrator(
        transcriber=_FakeTranscriber("x"),
        llm_stream=_slow_llm_factory(asyncio.Event()),
        tts=_fake_tts, player=player, model="m",
        vad_factory=lambda: vad, persona=persona,
    )
    orch._loop = asyncio.get_running_loop()
    orch._get_bargein_detector(1)   # ストリーム生成
    orch.request_bargein(1)
    assert vad.resets >= 1          # ストリーム切替で reset_states 相当が呼ばれる
