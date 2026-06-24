from talk_ai import config
from talk_ai.config import Config


def test_audio_constants():
    assert config.SAMPLE_RATE_HZ == 16000
    assert config.VAD_WINDOW_SAMPLES == 512
    assert config.DISCORD_SAMPLE_RATE_HZ == 48000
    assert config.DISCORD_CHANNELS == 2


def test_config_defaults():
    c = Config()
    assert c.ollama_url == "http://localhost:11434"
    assert c.tts_http_url == "http://localhost:50021"
    assert c.whisper_model == "large-v3-turbo"
    assert c.vad_silence_ms == 400
    assert c.bargein_trigger_ms == 250
    assert c.language == "ja"


def test_config_error_handling_defaults():
    c = Config()
    assert c.fallback_text.strip() != ""
    assert c.stt_timeout_s == 30.0
    assert c.tts_timeout_s == 15.0
    assert c.play_timeout_s == 60.0
