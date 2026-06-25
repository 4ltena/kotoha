import dataclasses

import pytest

from kotoha.config import Config, VAD_WINDOW_SAMPLES


def test_gptsovits_defaults():
    cfg = Config()
    assert cfg.gptsovits_url == "http://localhost:9880"
    assert cfg.gptsovits_ref_audio_path == ""
    assert cfg.gptsovits_prompt_text == ""
    assert cfg.gptsovits_text_lang == "ja"
    assert cfg.gptsovits_prompt_lang == "ja"
    assert cfg.gptsovits_speed_factor == 1.0


def test_local_audio_defaults():
    cfg = Config()
    assert cfg.local_user_id == 0
    assert cfg.input_device is None
    assert cfg.output_device is None
    assert cfg.mic_blocksize == VAD_WINDOW_SAMPLES
    assert cfg.mic_blocksize == 512


def test_overrides_apply():
    cfg = Config(
        gptsovits_url="http://gpu-host:9880",
        gptsovits_ref_audio_path="/data/ref/voice.wav",
        gptsovits_prompt_text="これは参照音声です。",
        gptsovits_speed_factor=1.2,
        local_user_id=42,
        input_device="MacBook Pro Microphone",
        output_device=3,
        mic_blocksize=1024,
    )
    assert cfg.gptsovits_url == "http://gpu-host:9880"
    assert cfg.gptsovits_ref_audio_path == "/data/ref/voice.wav"
    assert cfg.gptsovits_prompt_text == "これは参照音声です。"
    assert cfg.gptsovits_speed_factor == 1.2
    assert cfg.local_user_id == 42
    assert cfg.input_device == "MacBook Pro Microphone"
    assert cfg.output_device == 3
    assert cfg.mic_blocksize == 1024


def test_config_still_frozen():
    cfg = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.gptsovits_url = "http://evil:9880"  # type: ignore[misc]
