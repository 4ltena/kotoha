import functools

from kotoha import local_app
from kotoha.config import Config


def _cfg() -> Config:
    return Config(
        ollama_url="http://localhost:11434",
        gptsovits_url="http://localhost:9880",
        gptsovits_ref_audio_path="/srv/voice/ref.wav",
        gptsovits_prompt_text="参照音声のテキスト",
        gptsovits_text_lang="ja",
        gptsovits_prompt_lang="ja",
        gptsovits_speed_factor=1.0,
        local_user_id=0,
        input_device=None,
    )


def test_build_orchestrator_wires_tts_llm_player_vad(monkeypatch):
    captured = {}

    class _FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(local_app, "Orchestrator", _FakeOrch)

    cfg = _cfg()
    session = object()
    loop = object()
    transcriber = object()
    player = object()

    orch = local_app.build_orchestrator(
        cfg,
        session=session,
        loop=loop,
        transcriber=transcriber,
        player=player,
    )

    assert isinstance(orch, _FakeOrch)

    # --- tts は GPT-SoVITS synthesize への partial ---
    tts = captured["tts"]
    assert isinstance(tts, functools.partial)
    assert tts.func is local_app.synthesize
    assert tts.keywords["session"] is session
    assert tts.keywords["base_url"] == cfg.gptsovits_url
    assert tts.keywords["ref_audio_path"] == cfg.gptsovits_ref_audio_path
    assert tts.keywords["prompt_text"] == cfg.gptsovits_prompt_text
    assert tts.keywords["text_lang"] == cfg.gptsovits_text_lang
    assert tts.keywords["prompt_lang"] == cfg.gptsovits_prompt_lang
    assert tts.keywords["speed_factor"] == cfg.gptsovits_speed_factor
    # config.tts_timeout_s を HTTP 層(aiohttp)へも伝える
    import aiohttp
    assert isinstance(tts.keywords["timeout"], aiohttp.ClientTimeout)
    assert tts.keywords["timeout"].total == cfg.tts_timeout_s

    # --- llm_stream は Ollama stream_chat への partial ---
    llm = captured["llm_stream"]
    assert isinstance(llm, functools.partial)
    assert llm.func is local_app.stream_chat
    assert llm.keywords["base_url"] == cfg.ollama_url
    assert llm.keywords["session"] is session

    # --- 注入物がそのまま渡る ---
    assert captured["player"] is player
    assert captured["transcriber"] is transcriber
    assert captured["vad_factory"] is local_app.SileroVad
    assert captured["loop"] is loop

    # --- config 由来パラメータは個別 kwarg として明示注入(bot.py と同一) ---
    assert captured["model"] == cfg.ollama_model
    assert captured["vad_threshold"] == cfg.vad_threshold
    assert captured["vad_silence_ms"] == cfg.vad_silence_ms
    assert captured["bargein_trigger_ms"] == cfg.bargein_trigger_ms
    assert captured["history_max_turns"] == cfg.history_max_turns
    assert captured["fallback_text"] == cfg.fallback_text
    assert captured["stt_timeout"] == cfg.stt_timeout_s
    assert captured["tts_timeout"] == cfg.tts_timeout_s
    assert captured["play_timeout"] == cfg.play_timeout_s
    assert callable(captured["clock"])
    assert captured["place"] == cfg.openweather_default_city


def test_build_orchestrator_passes_events(monkeypatch):
    captured = {}

    class _FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(local_app, "Orchestrator", _FakeOrch)

    sentinel = object()
    local_app.build_orchestrator(
        _cfg(),
        session=object(),
        loop=object(),
        transcriber=object(),
        player=object(),
        events=sentinel,
    )
    assert captured["events"] is sentinel


def test_build_orchestrator_defaults_events_to_null(monkeypatch):
    from kotoha.events import NullEvents

    captured = {}

    class _FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(local_app, "Orchestrator", _FakeOrch)

    local_app.build_orchestrator(
        _cfg(),
        session=object(),
        loop=object(),
        transcriber=object(),
        player=object(),
    )
    assert isinstance(captured["events"], NullEvents)


def test_build_orchestrator_passes_memory():
    import asyncio
    from kotoha.config import Config
    from kotoha.local_app import build_orchestrator

    sentinel = object()

    class _Tr:
        def transcribe(self, audio):
            return ""

    class _Pl:
        def is_playing(self):
            return False

        def stop(self):
            pass

        async def play_and_wait(self, wav):
            return True

    loop = asyncio.new_event_loop()
    try:
        orch = build_orchestrator(
            Config(),
            session=None,
            loop=loop,
            transcriber=_Tr(),
            player=_Pl(),
            memory=sentinel,
        )
        assert orch.memory is sentinel
    finally:
        loop.close()
