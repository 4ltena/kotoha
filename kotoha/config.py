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
    llm_num_predict: int = 120          # 応答の生成トークン上限(独白・冗長の抑制。1〜2文向け)
    tts_http_url: str = "http://localhost:50021"
    tts_http_speaker: int = 1
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    language: str = "ja"
    # STT 幻聴対策: 無音らしいセグメント破棄の閾値と、既知の幻聴フレーズのブロックリスト。
    whisper_no_speech_threshold: float = 0.6
    whisper_log_prob_threshold: float = -1.0
    stt_hallucination_blocklist: tuple = (
        "ご視聴ありがとうございました",
        "ご清聴ありがとうございました",
        "最後までご視聴いただきありがとうございました",
        "チャンネル登録をお願いします",
        "次の動画でお会いしましょう",
    )
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
    # TTS 読み置換: (表記, 読み) の組。合成前に適用し固有名詞の読み・区切りを安定させる。
    tts_readings: tuple = (("つくよみ", "ツクヨミ"),)
    # --- API検索 (OpenWeather。キーは環境変数 OPENWEATHER_API_KEY) ---
    openweather_default_city: str = "Tokyo"
    openweather_units: str = "metric"
    openweather_lang: str = "ja"
    # --- 関係性パラメータ (kotoha/relationship/) ---
    relationship_enabled: bool = True
    relationship_path: str = "data/relationship.json"
    relationship_model: str = "qwen3.5:4b"      # 分析用ローカルLLM(背景)
    relationship_init_affection: int = 90
    relationship_init_friendship: int = 90
    relationship_init_trust: int = 90
    relationship_init_respect: int = 90
    relationship_init_mood: int = 40
    relationship_r18_threshold: int = 80         # affection がこれ以上で成人向け表現を許容
    relationship_r18_prompt_path: str = "data/r18_prompt.txt"   # 解禁時に読む非公開プロンプト(git 管理外。無ければ何も足さない)
    relationship_analyze_enabled: bool = True    # 毎ターン背景でLLM分析するか。False で値は固定のまま注入のみ(VRAM/速度優先)
    # --- リモート音声 (別端末のブラウザのマイク/スピーカーを使う) ---
    remote_audio_enabled: bool = False           # True で 5108 のリモートI/Oを使い、ローカルmic/spkは使わない
    remote_audio_host: str = "0.0.0.0"           # LAN の他端末から見えるよう全インターフェイス
    remote_audio_port: int = 5108
    remote_audio_cert_dir: str = "data/certs"    # 自己署名証明書(cert.pem/key.pem)の置き場(data/ は git管理外)
    remote_audio_token: str = ""                 # 接続トークン。空なら起動時に自動生成し URL に付けて表示
    remote_half_duplex: bool = True              # 再生中はマイク入力を無視(スピーカー音の回り込み=エコー誤認識を防ぐ)
    # --- ローカル音声 I/O (sounddevice) ---
    local_user_id: int = 0
    input_device: Optional[int | str] = None   # None=既定デバイス
    output_device: Optional[int | str] = None  # None=既定デバイス
    mic_blocksize: int = VAD_WINDOW_SAMPLES     # 512: 16kHz で silero-vad 1窓
    # --- デスクトップ・オーバーレイ (SP2) ---
    overlay_enabled: bool = False
    overlay_ws_host: str = "127.0.0.1"
    overlay_ws_port: int = 8770
    # --- 記憶レイヤー (docs/superpowers/specs/2026-06-26-memory-layers-design.md) ---
    memory_enabled: bool = True
    memory_path: str = "data/memory.json"
    memory_compress_model: str = "qwen3.5:4b"
    memory_compress_interval: int = 30      # N: 何ターンごとに圧縮するか
    memory_keep_recent_turns: int = 10      # W: コンテキストに残す直近ターン数
    memory_promote_threshold: int = 40      # M: 短期エントリ何件で昇格するか
    memory_gemini_model_priority: tuple = ("flash-lite", "flash", "gemma")
    memory_short_term_max: int = 60      # 短期エントリ保持上限(昇格無効時の無制限増加を防ぐ)
