from kotoha import config
from kotoha.config import Config, build_config


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
    assert c.llm_num_predict == 160
    assert c.max_sentences_per_turn == 2


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
    assert c.local_timezone == "Asia/Tokyo"
    assert c.local_place == ""


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


def test_screen_perception_defaults():
    from kotoha.config import Config
    c = Config()
    assert c.screen_perception_enabled is False
    assert c.screen_capture_backend == "mss"
    assert c.screen_capture_max_long_edge == 1024
    assert c.screen_normal_interval_s == 4.0
    assert c.screen_game_mode == "powersave"
    assert c.screen_game_realtime_interval_s == 0.5
    assert c.screen_summary_max_age_s == 30.0
    assert c.screen_game_detect_fullscreen is True
    assert c.screen_game_process_names == ()
    assert c.screen_game_poll_s == 2.0
    assert c.vlm_perception_url == ""
    assert c.vlm_perception_model == "qwen3.5:4b"
    assert c.vlm_perception_api == "openai"
    assert c.vlm_perception_timeout_s == 20.0
    assert "画面" in c.vlm_perception_prompt
    assert c.aux_llm_url == ""
    assert c.screen_change_hash_threshold == 4


def test_build_config_overrides_from_env(monkeypatch):
    from kotoha.config import build_config
    monkeypatch.setenv("OLLAMA_URL", "http://gpu:11434")
    monkeypatch.setenv("VLM_PERCEPTION_URL", "http://vii:1234")
    monkeypatch.setenv("AUX_LLM_URL", "http://vii:1234")
    monkeypatch.setenv("VLM_PERCEPTION_MODEL", "qwen3-vl:4b")
    monkeypatch.setenv("VLM_PERCEPTION_API", "ollama")
    monkeypatch.setenv("SCREEN_PERCEPTION_ENABLED", "true")
    monkeypatch.setenv("SCREEN_CAPTURE_BACKEND", "dxcam")
    monkeypatch.setenv("LOCAL_TIMEZONE", "America/New_York")
    monkeypatch.setenv("KOTOHA_PLACE", "大阪")
    c = build_config()
    assert c.ollama_url == "http://gpu:11434"
    assert c.vlm_perception_url == "http://vii:1234"
    assert c.aux_llm_url == "http://vii:1234"
    assert c.vlm_perception_model == "qwen3-vl:4b"
    assert c.vlm_perception_api == "ollama"
    assert c.screen_perception_enabled is True
    assert c.screen_capture_backend == "dxcam"
    assert c.local_timezone == "America/New_York"
    assert c.local_place == "大阪"
    assert c.vlm_perception_timeout_s == 20.0   # 未設定はデフォルトのまま


def test_build_config_defaults_when_env_unset(monkeypatch):
    from kotoha.config import build_config
    for k in ("OLLAMA_URL", "VLM_PERCEPTION_URL", "AUX_LLM_URL", "VLM_PERCEPTION_MODEL",
              "VLM_PERCEPTION_API", "SCREEN_PERCEPTION_ENABLED", "SCREEN_CAPTURE_BACKEND",
              "LOCAL_TIMEZONE", "KOTOHA_PLACE"):
        monkeypatch.delenv(k, raising=False)
    c = build_config()
    assert c.screen_perception_enabled is False
    assert c.vlm_perception_model == "qwen3.5:4b"
    assert c.ollama_url == "http://localhost:11434"
    assert c.vlm_perception_url == ""


def test_build_config_bool_parsing(monkeypatch):
    from kotoha.config import build_config
    monkeypatch.setenv("SCREEN_PERCEPTION_ENABLED", "0")
    assert build_config().screen_perception_enabled is False
    monkeypatch.setenv("SCREEN_PERCEPTION_ENABLED", "yes")
    assert build_config().screen_perception_enabled is True
    monkeypatch.setenv("SCREEN_PERCEPTION_ENABLED", "")   # 空はデフォルト維持
    assert build_config().screen_perception_enabled is False


def test_operation_defaults_are_safe():
    c = Config()
    assert c.operation_enabled is False
    assert c.operation_dry_run is True
    assert c.operation_app_allowlist == ()
    assert c.grounding_model == "holo2-8b"


def test_build_config_reads_operation_and_grounding_env():
    env = {
        "OPERATION_ENABLED": "true",
        "OPERATION_DRY_RUN": "false",
        "OPERATION_APP_ALLOWLIST": "chrome.exe, code.exe",
        "GROUNDING_URL": "http://localhost:11436",
        "GROUNDING_MODEL": "holo2-8b",
        "GROUNDING_TIMEOUT_S": "45",
    }
    c = build_config(env=env)
    assert c.operation_enabled is True
    assert c.operation_dry_run is False
    assert c.operation_app_allowlist == ("chrome.exe", "code.exe")
    assert c.grounding_url == "http://localhost:11436"
    assert c.grounding_timeout_s == 45.0


def test_screen_change_hash_threshold_default():
    from kotoha.config import Config
    assert Config().screen_change_hash_threshold == 4
