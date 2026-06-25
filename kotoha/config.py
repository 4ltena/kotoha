from dataclasses import dataclass
from typing import Optional

SAMPLE_RATE_HZ = 16000          # 内部音声: 16kHz mono float32
VAD_WINDOW_SAMPLES = 512        # silero-vad は 16kHz で正確に 512 samples
DISCORD_SAMPLE_RATE_HZ = 48000  # Discord PCM: 48kHz
DISCORD_CHANNELS = 2            # Discord PCM: stereo
FRAME_MS = 20                   # 1 パケット = 20ms


@dataclass(frozen=True)
class Config:
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:4b"
    tts_http_url: str = "http://localhost:50021"
    tts_http_speaker: int = 1
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    language: str = "ja"
    vad_threshold: float = 0.5
    vad_silence_ms: int = 400        # 無音 ~400ms で発話区切り
    bargein_trigger_ms: int = 250    # ~250ms 継続発話で barge-in
    history_max_turns: int = 20
    # --- エラー処理(設計書 §4) ---
    fallback_text: str = "ごめん、うまく聞き取れなかった。"
    stt_timeout_s: float = 30.0
    tts_timeout_s: float = 15.0
    play_timeout_s: float = 60.0
    # --- GPT-SoVITS (api_v2.py /tts) ---
    gptsovits_url: str = "http://localhost:9880"
    gptsovits_ref_audio_path: str = ""      # GPT-SoVITS サーバ上の参照音声パス
    gptsovits_prompt_text: str = ""         # ref_audio の文字起こし(任意)
    gptsovits_text_lang: str = "ja"
    gptsovits_prompt_lang: str = "ja"
    gptsovits_speed_factor: float = 1.0
    # --- ローカル音声 I/O (sounddevice) ---
    local_user_id: int = 0
    input_device: Optional[int | str] = None   # None=既定デバイス
    output_device: Optional[int | str] = None  # None=既定デバイス
    mic_blocksize: int = VAD_WINDOW_SAMPLES     # 512: 16kHz で silero-vad 1窓
