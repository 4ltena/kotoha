import numpy as np
from kotoha.orchestrator import Orchestrator
from kotoha.llm import persona


class _FakeTranscriber:
    def __init__(self, text):
        self._text = text

    def transcribe(self, audio):
        return self._text


def _make_llm(tokens):
    async def _llm(messages, *, model):
        for t in tokens:
            yield t

    return _llm


async def _fake_tts(text):
    return ("WAV:" + text).encode()


class _RecPlayer:
    def __init__(self):
        self.played = []

    def is_playing(self):
        return False

    def stop(self):
        pass

    async def play_and_wait(self, wav):
        self.played.append(wav)
        return True


class _FakeVad:
    def prob(self, frame):
        return 0.0

    def reset(self):
        pass


async def test_turn_pipeline_plays_each_sentence_and_records_history():
    player = _RecPlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["はい", "、", "元気", "です。", "また", "ね。"]),
        tts=_fake_tts,
        player=player,
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))

    assert player.played == [("WAV:" + "はい、元気です。").encode(),
                             ("WAV:" + "またね。").encode()]
    assert list(orch.history)[0] == {"role": "user", "content": "やあ"}
    assert list(orch.history)[-1] == {"role": "assistant", "content": "はい、元気です。またね。"}


async def test_empty_transcript_skips_turn():
    player = _RecPlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("   "),
        llm_stream=_make_llm(["x。"]),
        tts=_fake_tts,
        player=player,
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert player.played == []
    assert len(orch.history) == 0


async def test_stt_exception_is_caught_and_skips_turn():
    class _Boom:
        def transcribe(self, audio):
            raise RuntimeError("whisper down")

    player = _RecPlayer()
    orch = Orchestrator(
        transcriber=_Boom(),
        llm_stream=_make_llm(["x。"]),
        tts=_fake_tts,
        player=player,
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))   # 例外を握り潰し沈黙扱い
    assert player.played == []
    assert len(orch.history) == 0


async def test_tts_failure_triggers_fallback_speech():
    calls = []

    async def _bad_tts(text):
        calls.append(text)
        if text == "ダメ。":
            raise RuntimeError("tts_http down")
        return ("WAV:" + text).encode()

    player = _RecPlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["ダメ。"]),
        tts=_bad_tts,
        player=player,
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        fallback_text="ごめん。",
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    # 本文 TTS 失敗 -> フォールバック文を合成・再生
    assert player.played == [("WAV:" + "ごめん。").encode()]
    assert "ごめん。" in calls


class _RecEvents:
    def __init__(self):
        self.states = []

    def state(self, value):
        self.states.append(value)

    def mouth(self, level):
        pass


async def test_events_emitted_for_normal_turn():
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["はい。"]),
        tts=_fake_tts,
        player=_RecPlayer(),
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        events=_RecEvents() if False else _RecEvents(),
    )
    ev = orch._events
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert ev.states == ["thinking", "speaking", "idle"]


async def test_events_empty_transcript_emits_nothing():
    ev = _RecEvents()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("   "),
        llm_stream=_make_llm(["x。"]),
        tts=_fake_tts,
        player=_RecPlayer(),
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        events=ev,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert ev.states == []


async def test_events_speaking_emitted_on_tts_fallback():
    async def _bad_tts(text):
        if text == "ダメ。":
            raise RuntimeError("tts down")
        return ("WAV:" + text).encode()

    ev = _RecEvents()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["ダメ。"]),
        tts=_bad_tts,
        player=_RecPlayer(),
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        fallback_text="ごめん。",
        events=ev,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert ev.states == ["thinking", "speaking", "idle"]


class _FakeMemory:
    def __init__(self):
        self.users = []
        self.ended = []

    def add_user(self, text):
        self.users.append(text)

    def build_messages(self):
        return [{"role": "system", "content": "MEM"}, {"role": "user", "content": self.users[-1]}]

    def on_turn_end(self, text):
        self.ended.append(text)


async def test_memory_path_calls_add_user_and_on_turn_end():
    mem = _FakeMemory()
    player = _RecPlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["はい", "です。"]),
        tts=_fake_tts,
        player=player,
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        memory=mem,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert mem.users == ["やあ"]
    assert mem.ended == ["はいです。"]
    assert len(orch.history) == 0   # memory 経路では deque を使わない


async def test_stage_direction_parenthetical_not_spoken():
    # ト書きの括弧書きだけの文(（02:15 ごろ）)は TTS へ流さない。
    player = _RecPlayer()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["（02:15 ごろ）", "\n", "はい", "。"]),
        tts=_fake_tts,
        player=player,
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert player.played == [("WAV:" + "はい。").encode()]
