from kotoha import config
from kotoha.config import Config


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
    assert c.llm_num_predict == 120


def test_stt_hallucination_defaults():
    c = Config()
    assert c.whisper_no_speech_threshold == 0.6
    assert c.whisper_log_prob_threshold == -1.0
    assert "ご視聴ありがとうございました" in c.stt_hallucination_blocklist


def test_config_error_handling_defaults():
    c = Config()
    assert c.fallback_text.strip() != ""
    assert c.stt_timeout_s == 30.0
    assert c.tts_timeout_s == 15.0
    assert c.play_timeout_s == 60.0


def test_memory_defaults():
    from kotoha.config import Config
    c = Config()
    assert c.memory_enabled is True
    assert c.memory_path == "data/memory.json"
    assert c.memory_compress_model == "qwen3.5:4b"
    assert c.memory_compress_interval == 30
    assert c.memory_keep_recent_turns == 10
    assert c.memory_promote_threshold == 40
    assert c.memory_gemini_model_priority == ("flash-lite", "flash", "gemma")
    assert c.memory_short_term_max == 60


def test_tts_readings_default():
    assert Config().tts_readings == (("つくよみ", "ツクヨミ"),)


def test_openweather_defaults():
    c = Config()
    assert c.openweather_default_city == "Tokyo"
    assert c.openweather_units == "metric"
    assert c.openweather_lang == "ja"


def test_relationship_defaults():
    c = Config()
    assert c.relationship_enabled is True
    assert c.relationship_path == "data/relationship.json"
    assert c.relationship_model == "qwen3.5:4b"
    assert c.relationship_init_affection == 90
    assert c.relationship_init_friendship == 90
    assert c.relationship_init_trust == 90
    assert c.relationship_init_respect == 90
    assert c.relationship_init_mood == 40
    assert c.relationship_r18_threshold == 80
    assert c.relationship_analyze_enabled is True
    assert c.relationship_r18_prompt_path == "data/r18_prompt.txt"


def test_remote_audio_defaults():
    c = Config()
    assert c.remote_audio_enabled is False
    assert c.remote_audio_host == "0.0.0.0"
    assert c.remote_audio_port == 5108
    assert c.remote_audio_cert_dir == "data/certs"
    assert c.remote_half_duplex is True
