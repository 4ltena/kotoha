# フェーズ1: リアルタイム音声ループ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discord VC 内で「受信 → VAD → STT → フロント LLM → 文分割 → TTS → 再生」を低遅延でループさせ、barge-in と複数話者(ユーザー別受信)に対応する土台を作る。

**Architecture:** 各処理を I/F で分離した小モジュール(`kotoha/voice/*`, `kotoha/llm/*`)に切り出し、中央の `Orchestrator`(asyncio)が配線する。音声は受信スレッドから 16kHz/mono/float32 に正規化し、**VAD 推論は専用ワーカースレッドへ逃がして**確定イベント(発話区間/barge-in)だけイベントループへ marshalling する。ループ上では STT(executor)→LLM ストリーミング→文分割→TTS→再生を **3 段の asyncio キュー(文 → TTS 合成 → 再生)で真にパイプライン化**し、TTS 合成と再生を重ねて無音ギャップを抑える。**silero-vad は内部 LSTM 状態を持つステートフルモデルなので、VAD インスタンスはユーザー別・用途別(セグメンタ用/barge-in 用)に分離**し、発話区間確定・barge-in・ターン切替の各境界で `reset_states()` を呼ぶ。barge-in は再生中も割り込みユーザーの VAD を回し続け、検出時に LLM 生成キャンセル + 再生停止 + TTS/再生キュー破棄 + 割り込み冒頭(pre-roll)の引き継ぎを行う。各外部呼び出し(STT/LLM/TTS/再生)は try/except + タイムアウト + フォールバック発話で保護する。

**Tech Stack:** Python 3.11+ / discord.py[voice] + discord-ext-voice-recv(受信) / silero-vad(VAD) / faster-whisper large-v3-turbo(STT) / Ollama `/api/chat` ストリーミング(フロント LLM) / TTSサーバ HTTP(TTS) / aiohttp / numpy / pytest + pytest-asyncio。

> 設計書 §8 のモジュールは Python パッケージとして `kotoha/` 配下に置く(ハイフン不可のため)。例: 設計書の `voice/receiver.py` → `kotoha/voice/receiver.py`。フェーズ1スコープ外の `turntaking/`・`dispatch/`・`handlers/`・`tone_adjuster.py` は本計画では作らない。

## Global Constraints

- Python >= 3.11。bot 本体は RTX 4080 の CUDA ホストで動作(開発は macOS 可、CPU フォールバックあり)。
- 音声の内部表現は **16000 Hz / mono / float32(振幅 [-1.0, 1.0] 正規化)** に統一する。
- Discord から受信する PCM は **48000 Hz / stereo(2ch)/ 16-bit signed little-endian**。1 フレーム 20ms = 960 samples/ch = 3840 bytes。
- silero-vad は 16kHz で **正確に 512 samples(32ms)の torch.float32 テンソル(shape `(512,)`)** が必須。端数フレームは捨てる。**モデルはステートフル(内部 LSTM)**: 独立ストリーム間で必ず `model.reset_states()` を呼ぶ。本計画では VAD をユーザー別・用途別に分離し、(a) 発話区間確定後、(b) barge-in 時、(c) ターン/話者切替時に `reset()` を呼ぶ。
- **VAD 推論はイベントループ上で同期実行しない**。専用の単一ワーカースレッド(`ThreadPoolExecutor(max_workers=1)`)で回し、確定イベントだけ `loop.call_soon_threadsafe` でループへ渡す(Ollama ストリーム受信・再生スケジューリングをブロックしない)。
- faster-whisper に numpy 配列を渡す場合は `decode_audio` を通らないため、**float32 / mono / 16000 Hz / 振幅 [-1,1]** を自前で保証する。モデル名は `large-v3-turbo`、device=`cuda` なら compute_type=`float16`、device=`cpu` なら `int8`。`segments` は遅延ジェネレータなので反復して初めて実行される。STT は `run_in_executor` で実行し `asyncio.wait_for` で上限を設ける。
- Ollama: `http://localhost:11434`、`POST /api/chat`、ストリームは **NDJSON**。トークンは `obj["message"]["content"]`(ネスト)、終了は top-level `obj["done"] == True`。専用キャンセル API は無く、**HTTP 接続を閉じる(タスク cancel)** ことで生成停止。長命の共有 `aiohttp.ClientSession` を使う。
- TTSサーバ: `http://localhost:50021`。`POST /audio_query`(`text`/`speaker` は **クエリ文字列**、body は空)→ `POST /synthesis`(`speaker` はクエリ、AudioQuery JSON が **body**)。出力 WAV は既定 24000 Hz / mono / 16-bit。`speaker` は実体は style ID。合成は文単位で **共有 session** を使い、各呼び出しに `aiohttp.ClientTimeout` を設定する。
- Discord 再生: **`discord.FFmpegPCMAudio(io.BytesIO(wav), pipe=True)` を使う**(ffmpeg が 24kHz mono を 48kHz stereo へ自動リサンプル)。`discord.PCMAudio` は変換しないので 24kHz WAV を渡すと ~4 倍速の早口になる(地雷)。barge-in は `vc.play()` の前に必ず `vc.stop()`(同期で player をクリアするので `Already playing audio.` を回避)。
- discord-ext-voice-recv: 接続時 `cls=voice_recv.VoiceRecvClient` が必須。`AudioSink.write(self, user, data)` は **同期**で受信スレッドから 20ms ごとに呼ばれる。**ブロック・コルーチン直呼び禁止**。`wants_opus()` は False(=`data.pcm` に PCM)。`user` は None になりうる。`vc.listen(sink)` は await 不要。受信スレッド→処理は `Orchestrator.feed_audio`(threadsafe、内部で VAD ワーカースレッドへ submit)に渡す。
- **エラー処理(設計書 §4)**: STT/LLM/TTS/再生の各外部呼び出しを try/except で囲み、(1) STT 失敗・空テキストは沈黙扱いでスキップ、(2) LLM/TTS/API 失敗はログ + フォールバック発話(`Config.fallback_text`)を合成・再生、(3) 各段にタイムアウト(`stt_timeout_s`/`tts_timeout_s`/`play_timeout_s`)を設ける。TTSサーバ/Whisper の**死活監視**は起動時の疎通チェック(`health.check_services`)のみ本フェーズで実装し、プロセス再起動・常時ウォッチドッグはフェーズ1.x へ延期する(スコープ注記参照)。
- 外部サービス(Discord / GPU Whisper / Ollama / TTSサーバ / ffmpeg)が必要なテストは `@pytest.mark.integration` で分離し、既定の単体テスト実行から外す。**依存の段階導入**: 軽量依存(aiohttp/numpy)を base、重い ML(torch/torchaudio/faster-whisper/silero-vad)を `ml` extra、Discord 系を `voice` extra、テスト系を `dev` extra に分離し、各タスクで必要な extra だけ入れる。

---

### Task 1: プロジェクト雛形とConfig

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `kotoha/__init__.py`
- Create: `kotoha/voice/__init__.py`
- Create: `kotoha/llm/__init__.py`
- Create: `kotoha/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: なし
- Produces: 定数 `SAMPLE_RATE_HZ=16000`, `VAD_WINDOW_SAMPLES=512`, `DISCORD_SAMPLE_RATE_HZ=48000`, `DISCORD_CHANNELS=2`, `FRAME_MS=20`。`@dataclass(frozen=True) class Config` フィールド: `ollama_url:str`, `ollama_model:str`, `tts_http_url:str`, `tts_http_speaker:int`, `whisper_model:str`, `whisper_device:str`, `whisper_compute_type:str`, `language:str`, `vad_threshold:float`, `vad_silence_ms:int`, `bargein_trigger_ms:int`, `history_max_turns:int`, `fallback_text:str`, `stt_timeout_s:float`, `tts_timeout_s:float`, `play_timeout_s:float`。

- [ ] **Step 0: 最小ブートストラップ(pytest だけ先に入れる)**

> 最初の赤/緑は pure-Python の Config だけで回す。重い ML 依存は後続タスクで入れる(点17/18)。

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "pytest>=8.0" "pytest-asyncio>=0.23"
```

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py`:
```python
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


def test_config_error_handling_defaults():
    c = Config()
    assert c.fallback_text.strip() != ""
    assert c.stt_timeout_s == 30.0
    assert c.tts_timeout_s == 15.0
    assert c.play_timeout_s == 60.0
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha'`)
> Step 0 で pytest を入れているので、赤の理由は `pytest` 未インストールではなく `kotoha` 未作成になる(点17)。

- [ ] **Step 3: 最小実装**

`pyproject.toml`:
```toml
[project]
name = "kotoha"
version = "0.1.0"
requires-python = ">=3.11"
# base は軽量依存のみ。重い ML / Discord 系は extra へ分離(段階導入)。
dependencies = [
    "aiohttp>=3.9",
    "numpy>=1.24",
]

[project.optional-dependencies]
voice = [
    "discord.py[voice]>=2.4",
    "discord-ext-voice-recv>=0.5.2a179",
]
ml = [
    "torch>=1.12.0",
    "torchaudio>=0.12.0",
    "faster-whisper>=1.2.1",
    "silero-vad>=6.2.1",
]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "soundfile>=0.12"]
all = ["kotoha[voice,ml]"]

[tool.pytest.ini_options]
pythonpath = ["."]
asyncio_mode = "auto"
markers = [
    "integration: 外部サービス(Discord/GPU/Ollama/TTSサーバ/ffmpeg)が必要なテスト",
]
```

`requirements.txt`:
```
# --- base ---
aiohttp>=3.9
numpy>=1.24
# --- voice extra: discord-ext-voice-recv は alpha のため --pre が必要 ---
#   python -m pip install -e ".[voice]" --pre
discord.py[voice]>=2.4
discord-ext-voice-recv>=0.5.2a179
# --- ml extra(数GB) ---
torch>=1.12.0
torchaudio>=0.12.0
faster-whisper>=1.2.1
silero-vad>=6.2.1
# --- dev ---
pytest>=8.0
pytest-asyncio>=0.23
soundfile>=0.12
```

`kotoha/__init__.py`, `kotoha/voice/__init__.py`, `kotoha/llm/__init__.py`: 空ファイル。

`kotoha/config.py`:
```python
from dataclasses import dataclass

SAMPLE_RATE_HZ = 16000          # 内部音声: 16kHz mono float32
VAD_WINDOW_SAMPLES = 512        # silero-vad は 16kHz で正確に 512 samples
DISCORD_SAMPLE_RATE_HZ = 48000  # Discord PCM: 48kHz
DISCORD_CHANNELS = 2            # Discord PCM: stereo
FRAME_MS = 20                   # 1 パケット = 20ms


@dataclass(frozen=True)
class Config:
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
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
```

- [ ] **Step 4: 緑を確認(軽量インストール)**

Run: `python -m pip install -e ".[dev]"` then `python -m pytest tests/test_config.py -v`
Expected: PASS (3 passed)
> `.[dev]` は base(aiohttp/numpy)+ テスト系のみ。torch/discord 等の数GB 依存はこの時点では入れない(点18)。

- [ ] **Step 5: commit**

```bash
git add pyproject.toml requirements.txt kotoha/ tests/test_config.py
git commit -m "feat: プロジェクト雛形とConfigを追加"
```

---

### Task 2: 音声変換ユーティリティ (48kHz stereo PCM → 16kHz mono float32)

**Files:**
- Create: `kotoha/voice/audio_utils.py`
- Test: `tests/voice/test_audio_utils.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `resample_linear(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray`(線形補間、float32 を返す)
  - `pcm_s16le_to_float32_mono_16k(pcm: bytes, src_rate: int = 48000, src_channels: int = 2, dst_rate: int = 16000) -> np.ndarray`(Discord s16le PCM → 16kHz mono float32、振幅 [-1,1])

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_audio_utils.py`:
```python
import numpy as np
from kotoha.voice.audio_utils import resample_linear, pcm_s16le_to_float32_mono_16k


def test_resample_linear_decimates_48k_to_16k():
    x = np.array([0, 1, 2, 3, 4, 5], dtype=np.float32)
    out = resample_linear(x, 48000, 16000)
    assert out.dtype == np.float32
    assert out.shape == (2,)            # round(6 * 16000/48000) = 2
    np.testing.assert_allclose(out, [0.0, 5.0])


def test_resample_same_rate_is_passthrough():
    x = np.array([0.1, 0.2], dtype=np.float32)
    np.testing.assert_allclose(resample_linear(x, 16000, 16000), x)


def test_pcm_stereo_48k_to_mono_16k_float32():
    # 6 stereo pairs, all value 16384 -> mono 0.5, 48k->16k -> 2 samples
    i16 = np.full(12, 16384, dtype=np.int16)
    out = pcm_s16le_to_float32_mono_16k(i16.tobytes())
    assert out.dtype == np.float32
    assert out.shape == (2,)
    np.testing.assert_allclose(out, [0.5, 0.5], atol=1e-4)


def test_pcm_empty_returns_empty():
    out = pcm_s16le_to_float32_mono_16k(b"")
    assert out.dtype == np.float32
    assert out.shape == (0,)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_audio_utils.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.voice.audio_utils'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/audio_utils.py`:
```python
import numpy as np


def resample_linear(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """線形補間でリサンプル。float32 を返す。

    注意: これは **アンチエイリアス用ローパスを掛けない**単純な線形補間。
    48kHz->16kHz では 8kHz 超の成分が折り返す可能性がある(faster-whisper の
    要件 float32/mono/16k/[-1,1] は満たすが、品質を重視するなら
    scipy.signal.resample_poly や torchaudio のリサンプラ(ローパス付き)へ
    置換すること)。フェーズ1では音声会話用途として許容(点13)。
    """
    x = np.asarray(x, dtype=np.float32)
    if len(x) == 0:
        return np.zeros(0, dtype=np.float32)
    if src_rate == dst_rate:
        return x
    dst_len = int(round(len(x) * dst_rate / src_rate))
    if dst_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0.0, len(x) - 1, num=dst_len)
    return np.interp(src_idx, np.arange(len(x)), x).astype(np.float32)


def pcm_s16le_to_float32_mono_16k(
    pcm: bytes,
    src_rate: int = 48000,
    src_channels: int = 2,
    dst_rate: int = 16000,
) -> np.ndarray:
    """Discord s16le PCM を 16kHz mono float32([-1,1])へ変換。"""
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    i16 = np.frombuffer(pcm, dtype=np.int16)
    if src_channels == 2:
        if len(i16) % 2:
            i16 = i16[:-1]
        mono = i16.astype(np.float32).reshape(-1, 2).mean(axis=1) / 32768.0
    else:
        mono = i16.astype(np.float32) / 32768.0
    return resample_linear(mono, src_rate, dst_rate)
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_audio_utils.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/audio_utils.py tests/voice/test_audio_utils.py
git commit -m "feat: 48kHz stereo PCM→16kHz mono float32 変換ユーティリティ"
```

---

### Task 3: Silero VAD ラッパと発話区間セグメンタ

> このタスクから silero-vad/torch が必要。`python -m pip install -e ".[ml,dev]"` を実行しておく(点18)。

**Files:**
- Create: `kotoha/voice/vad.py`
- Test: `tests/voice/test_vad.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `class SileroVad: __init__(self, sample_rate: int = 16000)`, `prob(self, frame: np.ndarray) -> float`(frame は正確に 512 samples float32、shape `(512,)`), `reset(self) -> None`(= `model.reset_states()`)。**ステートフル契約**: 同一インスタンスは 1 つの連続ストリーム専用。独立ストリーム間で `reset()` を呼ぶこと。
  - `class VadSegmenter: __init__(self, prob_fn: Callable[[np.ndarray], float], *, threshold: float = 0.5, silence_ms: int = 400, sample_rate: int = 16000, window: int = 512, reset_fn: Callable[[], None] | None = None)`, `push(self, audio: np.ndarray) -> list[np.ndarray]`(確定した発話区間を返す。区間確定時に `reset_fn()` を呼ぶ), `reset(self) -> None`(バッファ初期化 + `reset_fn()`)

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_vad.py`:
```python
import numpy as np
import pytest
from kotoha.voice.vad import VadSegmenter


def _scripted(probs):
    it = iter(probs)
    return lambda frame: next(it)


def test_segmenter_emits_one_utterance_after_silence():
    # 3 speech frames then 2 silence frames; silence_ms=64ms -> 2 frames (512/16k=32ms)
    probs = [0.9, 0.9, 0.9, 0.1, 0.1]
    seg = VadSegmenter(_scripted(probs), threshold=0.5, silence_ms=64)
    out = seg.push(np.zeros(5 * 512, dtype=np.float32))
    assert len(out) == 1
    assert out[0].shape == (5 * 512,)          # speech + trailing silence frames
    assert out[0].dtype == np.float32


def test_segmenter_no_emit_while_still_speaking():
    probs = [0.9, 0.9, 0.9]
    seg = VadSegmenter(_scripted(probs), threshold=0.5, silence_ms=64)
    assert seg.push(np.zeros(3 * 512, dtype=np.float32)) == []


def test_segmenter_drops_partial_trailing_frame():
    seg = VadSegmenter(lambda f: 0.0, threshold=0.5, silence_ms=64)
    # 700 samples -> 1 full 512 frame processed, 188 buffered (dropped from this call)
    out = seg.push(np.zeros(700, dtype=np.float32))
    assert out == []


def test_segmenter_calls_reset_fn_on_utterance_finalization():
    resets = []
    probs = [0.9, 0.9, 0.1, 0.1]
    seg = VadSegmenter(
        _scripted(probs), threshold=0.5, silence_ms=64,
        reset_fn=lambda: resets.append(1),
    )
    seg.push(np.zeros(4 * 512, dtype=np.float32))
    assert resets == [1]            # 区間確定でストリーム切替 -> VAD 状態リセット


# --- integration: 実 silero-vad モデルでテンソル形状/値域/区間検出を検証(点15) ---
@pytest.mark.integration
def test_real_silero_prob_shape_and_range():
    from kotoha.voice.vad import SileroVad

    vad = SileroVad()
    p = vad.prob(np.zeros(512, dtype=np.float32))
    assert isinstance(p, float) and 0.0 <= p <= 1.0
    vad.reset()


@pytest.mark.integration
def test_real_silero_segmenter_no_utterance_on_silence():
    from kotoha.voice.vad import SileroVad

    vad = SileroVad()
    seg = VadSegmenter(vad.prob, reset_fn=vad.reset, silence_ms=200)
    out = seg.push(np.zeros(30 * 512, dtype=np.float32))   # 無音 -> 区間は出ない
    assert out == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_vad.py -v -m "not integration"`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.voice.vad'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/vad.py`:
```python
from typing import Callable, Optional

import numpy as np


def _frames_for_ms(ms: int, window: int, sample_rate: int) -> int:
    frame_ms = window / sample_rate * 1000.0
    return max(1, int(ms / frame_ms))


class SileroVad:
    """silero-vad ラッパ。frame は正確に `window` samples の float32(shape (512,))。

    ステートフル(内部 LSTM)。1 インスタンス = 1 連続ストリーム専用。
    独立ストリーム(別話者・別用途・新発話)を処理する前に reset() を呼ぶ。
    """

    def __init__(self, sample_rate: int = 16000):
        from silero_vad import load_silero_vad
        import torch

        self._torch = torch
        self._model = load_silero_vad()
        self._sr = sample_rate

    def prob(self, frame: np.ndarray) -> float:
        # frame: np.ndarray shape (512,) -> torch.float32 tensor
        t = self._torch.as_tensor(frame, dtype=self._torch.float32)
        return self._model(t, self._sr).item()   # tensor -> Python float in [0,1]

    def reset(self) -> None:
        self._model.reset_states()


class VadSegmenter:
    """16kHz float32 を流し込み、無音で区切れた発話区間を返す。

    区間確定時(=ストリーム切替)に reset_fn() を呼び、背後の VAD 状態を初期化する。
    """

    def __init__(
        self,
        prob_fn: Callable[[np.ndarray], float],
        *,
        threshold: float = 0.5,
        silence_ms: int = 400,
        sample_rate: int = 16000,
        window: int = 512,
        reset_fn: Optional[Callable[[], None]] = None,
    ):
        self._prob_fn = prob_fn
        self._reset_fn = reset_fn
        self._threshold = threshold
        self._window = window
        self._silence_frames = _frames_for_ms(silence_ms, window, sample_rate)
        self._tail = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._silence_count = 0
        self._buf: list[np.ndarray] = []

    def push(self, audio: np.ndarray) -> list[np.ndarray]:
        self._tail = np.concatenate([self._tail, np.asarray(audio, dtype=np.float32)])
        out: list[np.ndarray] = []
        while len(self._tail) >= self._window:
            frame = self._tail[: self._window]
            self._tail = self._tail[self._window :]
            if self._prob_fn(frame) >= self._threshold:
                if not self._in_speech:
                    self._in_speech = True
                    self._buf = []
                self._buf.append(frame)
                self._silence_count = 0
            elif self._in_speech:
                self._buf.append(frame)
                self._silence_count += 1
                if self._silence_count >= self._silence_frames:
                    out.append(np.concatenate(self._buf))
                    self._in_speech = False
                    self._silence_count = 0
                    self._buf = []
                    if self._reset_fn is not None:
                        self._reset_fn()   # 区間確定 = ストリーム切替 -> silero 状態リセット
        return out

    def reset(self) -> None:
        self._tail = np.zeros(0, dtype=np.float32)
        self._in_speech = False
        self._silence_count = 0
        self._buf = []
        if self._reset_fn is not None:
            self._reset_fn()
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_vad.py -v -m "not integration"`
Expected: PASS (4 passed)
> 実モデルを使う 2 本は `python -m pytest tests/voice/test_vad.py -m integration` で別途検証(silero-vad ダウンロードあり)。

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/vad.py tests/voice/test_vad.py
git commit -m "feat: Silero VADラッパ(ステートフル/reset対応)と発話区間セグメンタ"
```

---

### Task 4: Barge-in 検出器

**Files:**
- Modify: `kotoha/voice/vad.py`(`BargeInDetector` を追記)
- Test: `tests/voice/test_bargein_detector.py`

**Interfaces:**
- Consumes: なし(同ファイル内の `_frames_for_ms` を再利用)
- Produces: `class BargeInDetector: __init__(self, prob_fn, *, threshold: float = 0.5, trigger_ms: int = 250, sample_rate: int = 16000, window: int = 512, reset_fn: Callable[[], None] | None = None)`, `push(self, audio: np.ndarray) -> bool`(連続発話が trigger に達した瞬間に一度だけ True), `drain(self) -> np.ndarray`(onset 以降に蓄積した発話フレームを返してクリア。barge-in 後にセグメンタへ pre-roll を引き継ぐ用), `reset(self) -> None`(バッファ初期化 + `reset_fn()`)

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_bargein_detector.py`:
```python
import numpy as np
from kotoha.voice.vad import BargeInDetector


def _scripted(probs):
    it = iter(probs)
    return lambda frame: next(it)


def test_fires_once_when_sustained_speech_reaches_trigger():
    # trigger_ms=64 -> 2 consecutive speech frames
    probs = [0.1, 0.9, 0.9]
    det = BargeInDetector(_scripted(probs), threshold=0.5, trigger_ms=64)
    assert det.push(np.zeros(3 * 512, dtype=np.float32)) is True


def test_does_not_fire_on_silence():
    det = BargeInDetector(lambda f: 0.1, threshold=0.5, trigger_ms=64)
    assert det.push(np.zeros(4 * 512, dtype=np.float32)) is False


def test_resets_consecutive_count_on_gap():
    # speech, gap, speech -> never 2-in-a-row
    probs = [0.9, 0.1, 0.9, 0.1]
    det = BargeInDetector(_scripted(probs), threshold=0.5, trigger_ms=64)
    assert det.push(np.zeros(4 * 512, dtype=np.float32)) is False


def test_drain_returns_accumulated_speech_and_clears():
    probs = [0.9, 0.9, 0.9]
    det = BargeInDetector(_scripted(probs), threshold=0.5, trigger_ms=64)
    det.push(np.zeros(3 * 512, dtype=np.float32))
    pre = det.drain()
    assert pre.dtype == np.float32
    assert pre.shape == (3 * 512,)        # onset 以降の発話フレーム
    assert det.drain().shape == (0,)      # 2 回目は空


def test_reset_calls_reset_fn():
    resets = []
    det = BargeInDetector(lambda f: 0.1, reset_fn=lambda: resets.append(1))
    det.reset()
    assert resets == [1]
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_bargein_detector.py -v`
Expected: FAIL (`ImportError: cannot import name 'BargeInDetector'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/vad.py` の末尾に追記:
```python
class BargeInDetector:
    """再生中に流し込み、連続発話が trigger に達した瞬間に一度だけ True。

    onset 以降の発話フレームを蓄積し、drain() で取り出せる(barge-in 後に
    割り込み冒頭をセグメンタへ pre-roll として引き継ぐため)。
    """

    def __init__(
        self,
        prob_fn: Callable[[np.ndarray], float],
        *,
        threshold: float = 0.5,
        trigger_ms: int = 250,
        sample_rate: int = 16000,
        window: int = 512,
        reset_fn: Optional[Callable[[], None]] = None,
    ):
        self._prob_fn = prob_fn
        self._reset_fn = reset_fn
        self._threshold = threshold
        self._window = window
        self._trigger = _frames_for_ms(trigger_ms, window, sample_rate)
        self._tail = np.zeros(0, dtype=np.float32)
        self._count = 0
        self._fired = False
        self._speech: list[np.ndarray] = []

    def push(self, audio: np.ndarray) -> bool:
        self._tail = np.concatenate([self._tail, np.asarray(audio, dtype=np.float32)])
        fired = False
        while len(self._tail) >= self._window:
            frame = self._tail[: self._window]
            self._tail = self._tail[self._window :]
            if self._prob_fn(frame) >= self._threshold:
                self._count += 1
                self._speech.append(frame)
                if self._count >= self._trigger and not self._fired:
                    self._fired = True
                    fired = True
            else:
                self._count = 0
                self._fired = False
                self._speech = []
        return fired

    def drain(self) -> np.ndarray:
        buf = np.concatenate(self._speech) if self._speech else np.zeros(0, dtype=np.float32)
        self._speech = []
        return buf

    def reset(self) -> None:
        self._tail = np.zeros(0, dtype=np.float32)
        self._count = 0
        self._fired = False
        self._speech = []
        if self._reset_fn is not None:
            self._reset_fn()
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_bargein_detector.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/vad.py tests/voice/test_bargein_detector.py
git commit -m "feat: barge-in用の連続発話検出器(pre-roll引き継ぎ対応)"
```

---

### Task 5: STT (faster-whisper) ラッパ

> faster-whisper が必要。`.[ml,dev]` が入っていること。

**Files:**
- Create: `kotoha/voice/stt.py`
- Test: `tests/voice/test_stt.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `def build_whisper(model_size: str = "large-v3-turbo", device: str = "cuda", compute_type: str = "float16")`(`WhisperModel` を生成)
  - `class Transcriber: __init__(self, model, *, language: str = "ja", beam_size: int = 5)`, `transcribe(self, audio: np.ndarray) -> str`(audio は float32 mono 16k、認識テキストを strip して返す。同期。Orchestrator 側で executor + timeout で実行)

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_stt.py`:
```python
import numpy as np
import pytest
from kotoha.voice.stt import Transcriber


class _Seg:
    def __init__(self, text):
        self.text = text


class _FakeWhisper:
    def __init__(self):
        self.last_kwargs = None

    def transcribe(self, audio, **kwargs):
        self.last_kwargs = kwargs
        assert audio.dtype == np.float32
        return iter([_Seg("こんにちは"), _Seg("世界")]), object()


def test_transcribe_joins_segments_and_strips():
    fake = _FakeWhisper()
    t = Transcriber(fake, language="ja")
    out = t.transcribe(np.zeros(16000, dtype=np.float32))
    assert out == "こんにちは世界"
    assert fake.last_kwargs["language"] == "ja"
    assert fake.last_kwargs["beam_size"] == 5


def test_transcribe_empty_segments_returns_empty_string():
    class _Empty:
        def transcribe(self, audio, **kwargs):
            return iter([]), object()

    assert Transcriber(_Empty()).transcribe(np.zeros(16000, dtype=np.float32)) == ""


@pytest.mark.integration
def test_real_whisper_transcribes_silence_to_str():
    from kotoha.voice.stt import build_whisper

    model = build_whisper("tiny", device="cpu", compute_type="int8")
    out = Transcriber(model).transcribe(np.zeros(16000, dtype=np.float32))
    assert isinstance(out, str)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_stt.py -v -m "not integration"`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.voice.stt'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/stt.py`:
```python
import numpy as np


def build_whisper(
    model_size: str = "large-v3-turbo",
    device: str = "cuda",
    compute_type: str = "float16",
):
    from faster_whisper import WhisperModel

    # GPU: device="cuda"/compute_type="float16"、CPU フォールバック: "cpu"/"int8"
    return WhisperModel(model_size, device=device, compute_type=compute_type)


class Transcriber:
    """faster-whisper ラッパ。numpy(float32/mono/16k/[-1,1])をそのまま渡す
    (ndarray は decode_audio をバイパスするので形式は呼び出し側保証)。"""

    def __init__(self, model, *, language: str = "ja", beam_size: int = 5):
        self._model = model
        self._language = language
        self._beam_size = beam_size

    def transcribe(self, audio: np.ndarray) -> str:
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio, language=self._language, beam_size=self._beam_size
        )
        # segments は遅延ジェネレータ -> 反復して初めて推論が走る
        return "".join(seg.text for seg in segments).strip()
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_stt.py -v -m "not integration"`
Expected: PASS (2 passed, 1 deselected)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/stt.py tests/voice/test_stt.py
git commit -m "feat: faster-whisper STTラッパ"
```

---

### Task 6: ユーザー別音声受信シンク (discord-ext-voice-recv)

> discord 系が必要。`python -m pip install -e ".[voice,dev]" --pre` を実行(discord-ext-voice-recv は alpha)。

**Files:**
- Create: `kotoha/voice/receiver.py`
- Test: `tests/voice/test_receiver.py`

**Interfaces:**
- Consumes: `pcm_s16le_to_float32_mono_16k`(Task 2)
- Produces: `class PerUserSink(voice_recv.AudioSink): __init__(self, on_audio: Callable[[int, np.ndarray], None], *, src_rate: int = 48000, src_channels: int = 2)`, `wants_opus(self) -> bool`(False), `write(self, user, data) -> None`(同期; `user` None / 空 pcm はスキップ、それ以外は変換して `on_audio(user.id, audio)`), `cleanup(self) -> None`

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_receiver.py`:
```python
import types
import numpy as np
from kotoha.voice.receiver import PerUserSink


def _data(pcm):
    return types.SimpleNamespace(pcm=pcm)


def test_wants_opus_false():
    assert PerUserSink(lambda uid, a: None).wants_opus() is False


def test_write_converts_and_dispatches_per_user():
    captured = []
    sink = PerUserSink(lambda uid, a: captured.append((uid, a)))
    # 20ms stereo 48k frame = 3840 bytes of zeros
    sink.write(types.SimpleNamespace(id=42), _data(b"\x00\x00" * 1920))
    assert len(captured) == 1
    uid, audio = captured[0]
    assert uid == 42
    assert audio.dtype == np.float32
    assert audio.shape == (320,)          # 960 mono samples 48k -> 16k = 320


def test_write_skips_none_user_and_empty_pcm():
    captured = []
    sink = PerUserSink(lambda uid, a: captured.append((uid, a)))
    sink.write(None, _data(b"\x00\x00" * 1920))      # user None -> skip
    sink.write(types.SimpleNamespace(id=1), _data(b""))  # empty pcm -> skip
    assert captured == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_receiver.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.voice.receiver'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/receiver.py`:
```python
from typing import Callable

import numpy as np
from discord.ext import voice_recv

from .audio_utils import pcm_s16le_to_float32_mono_16k


class PerUserSink(voice_recv.AudioSink):
    """ユーザー別に PCM を 16kHz mono float32 へ変換して on_audio に渡す。

    write は受信スレッドから同期で呼ばれる。重い処理・コルーチンはここで
    やらず、on_audio(= Orchestrator.feed_audio, threadsafe)へ即座に渡す。
    """

    def __init__(
        self,
        on_audio: Callable[[int, np.ndarray], None],
        *,
        src_rate: int = 48000,
        src_channels: int = 2,
    ):
        super().__init__()   # AudioSink.__init__ を必ず呼ぶ
        self._on_audio = on_audio
        self._src_rate = src_rate
        self._src_channels = src_channels

    def wants_opus(self) -> bool:
        return False  # -> data.pcm に 48kHz/stereo/16-bit PCM

    def write(self, user, data) -> None:
        if user is None:
            return  # SSRC->member 未解決。フェーズ1では捨てる
        pcm = data.pcm
        if not pcm:
            return
        audio = pcm_s16le_to_float32_mono_16k(
            pcm, src_rate=self._src_rate, src_channels=self._src_channels
        )
        if len(audio):
            self._on_audio(user.id, audio)

    def cleanup(self) -> None:
        return None
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_receiver.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/receiver.py tests/voice/test_receiver.py
git commit -m "feat: ユーザー別音声受信シンク(PerUserSink)"
```

---

### Task 7: ペルソナと フロントLLMストリーミングクライアント (Ollama)

**Files:**
- Create: `kotoha/llm/persona.py`
- Create: `kotoha/llm/front_client.py`
- Test: `tests/llm/test_persona.py`
- Test: `tests/llm/test_front_client.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `persona.SYSTEM_PROMPT: str`、`persona.build_messages(history: list[dict]) -> list[dict]`(先頭に system を付与した messages を返す)
  - `front_client.parse_chat_line(line: bytes) -> tuple[str, bool]`(NDJSON 1 行 → `(content_piece, done)`、空行は `("", False)`)
  - `async front_client.stream_chat(messages: list[dict], *, model: str, base_url: str = "http://localhost:11434", session: aiohttp.ClientSession | None = None) -> AsyncIterator[str]`(増分トークン文字列を yield)

> persona と front_client は独立ユニットなので、それぞれの緑直後に commit を分ける(点20)。

- [ ] **Step 1: 失敗するテストを書く(persona)**

`tests/llm/test_persona.py`:
```python
from kotoha.llm import persona


def test_build_messages_prepends_system():
    history = [{"role": "user", "content": "やあ"}]
    msgs = persona.build_messages(history)
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == persona.SYSTEM_PROMPT
    assert msgs[1:] == history


def test_build_messages_does_not_mutate_input():
    history = [{"role": "user", "content": "x"}]
    persona.build_messages(history)
    assert history == [{"role": "user", "content": "x"}]
```

- [ ] **Step 2: 失敗を確認(persona)**

Run: `python -m pytest tests/llm/test_persona.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.llm.persona'`)

- [ ] **Step 3: 最小実装(persona)**

`kotoha/llm/persona.py`:
```python
SYSTEM_PROMPT = (
    "あなたは音声で雑談する気さくな相棒です。"
    "応答はすべて声で読み上げられるので、短く・口語的に・1〜3文で話してください。"
    "箇条書きや記号の羅列、長い説明は避け、自然な話し言葉で返してください。"
)


def build_messages(history: list[dict]) -> list[dict]:
    """会話履歴の先頭に system プロンプトを付けた messages を返す。"""
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history]
```

- [ ] **Step 4: 緑を確認 & commit(persona)**

Run: `python -m pytest tests/llm/test_persona.py -v` → PASS (2 passed)
```bash
git add kotoha/llm/persona.py tests/llm/test_persona.py
git commit -m "feat: フロントLLM用ペルソナ(system prompt)"
```

- [ ] **Step 5: 失敗するテストを書く(front_client)**

`tests/llm/test_front_client.py`:
```python
import pytest
from kotoha.llm.front_client import parse_chat_line, stream_chat


def test_parse_intermediate_chunk():
    line = (
        b'{"model":"llama3.2","created_at":"x",'
        b'"message":{"role":"assistant","content":"The"},"done":false}'
    )
    assert parse_chat_line(line) == ("The", False)


def test_parse_final_chunk():
    line = (
        b'{"model":"llama3.2","created_at":"y",'
        b'"message":{"role":"assistant","content":""},"done":true}'
    )
    assert parse_chat_line(line) == ("", True)


def test_parse_blank_line():
    assert parse_chat_line(b"  ") == ("", False)


@pytest.mark.integration
async def test_stream_chat_real_ollama():
    msgs = [{"role": "user", "content": "1と2を足すと?"}]
    pieces = []
    async for piece in stream_chat(msgs, model="qwen2.5:7b-instruct"):
        pieces.append(piece)
    assert "".join(pieces).strip() != ""
```

- [ ] **Step 6: 失敗を確認(front_client)**

Run: `python -m pytest tests/llm/test_front_client.py -v -m "not integration"`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.llm.front_client'`)

- [ ] **Step 7: 最小実装(front_client)**

`kotoha/llm/front_client.py`:
```python
import json
from typing import AsyncIterator

import aiohttp


def parse_chat_line(line: bytes) -> tuple[str, bool]:
    """Ollama /api/chat の NDJSON 1 行を (content_piece, done) に変換。
    トークンは obj['message']['content'](ネスト)、終了は top-level 'done'。"""
    line = line.strip()
    if not line:
        return "", False
    obj = json.loads(line)
    piece = obj.get("message", {}).get("content", "")
    return piece, bool(obj.get("done"))


async def stream_chat(
    messages: list[dict],
    *,
    model: str,
    base_url: str = "http://localhost:11434",
    session: aiohttp.ClientSession | None = None,
) -> AsyncIterator[str]:
    """増分トークン文字列を yield。タスク cancel で接続が閉じ生成停止。
    session を渡せば長命の共有接続を使う(渡さなければ都度生成・破棄)。"""
    payload = {"model": model, "messages": messages, "stream": True}
    timeout = aiohttp.ClientTimeout(total=None, sock_read=300)
    own = session is None
    sess = session or aiohttp.ClientSession(timeout=timeout)
    try:
        async with sess.post(f"{base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for raw in resp.content:   # NDJSON: 1 行 = 1 JSON
                piece, done = parse_chat_line(raw)
                if piece:
                    yield piece
                if done:
                    return
    finally:
        if own:
            await sess.close()
```

- [ ] **Step 8: 緑を確認(front_client)**

Run: `python -m pytest tests/llm/test_front_client.py -v -m "not integration"`
Expected: PASS (3 passed, 1 deselected)

- [ ] **Step 9: commit(front_client)**

```bash
git add kotoha/llm/front_client.py tests/llm/test_front_client.py
git commit -m "feat: Ollamaストリーミングフロントクライアント(共有session対応)"
```

---

### Task 8: ストリーム→文分割 (SentenceSplitter)

**Files:**
- Create: `kotoha/llm/sentence_splitter.py`
- Test: `tests/llm/test_sentence_splitter.py`

**Interfaces:**
- Consumes: なし
- Produces: `class SentenceSplitter: __init__(self, endings: str = "。．！？!?\n")`, `push(self, token: str) -> list[str]`(確定文のリスト、句点込み・strip 済み), `flush(self) -> str`(残バッファを返してクリア)

- [ ] **Step 1: 失敗するテストを書く**

`tests/llm/test_sentence_splitter.py`:
```python
from kotoha.llm.sentence_splitter import SentenceSplitter


def test_emits_sentence_on_japanese_period():
    s = SentenceSplitter()
    assert s.push("こんにちは") == []
    assert s.push("。元気") == ["こんにちは。"]
    assert s.push("ですか?") == ["元気ですか?"]


def test_multiple_sentences_in_one_token():
    s = SentenceSplitter()
    assert s.push("はい。いいえ。") == ["はい。", "いいえ。"]


def test_flush_returns_remainder():
    s = SentenceSplitter()
    s.push("途中まで")
    assert s.flush() == "途中まで"
    assert s.flush() == ""


def test_whitespace_only_buffer_not_emitted():
    s = SentenceSplitter()
    assert s.push("  \n") == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/llm/test_sentence_splitter.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.llm.sentence_splitter'`)

- [ ] **Step 3: 最小実装**

`kotoha/llm/sentence_splitter.py`:
```python
class SentenceSplitter:
    """トークンストリームを句点境界で文に区切る。"""

    def __init__(self, endings: str = "。．！？!?\n"):
        self._endings = set(endings)
        self._buf: list[str] = []

    def push(self, token: str) -> list[str]:
        out: list[str] = []
        for ch in token:
            self._buf.append(ch)
            if ch in self._endings:
                sentence = "".join(self._buf).strip()
                if sentence:
                    out.append(sentence)
                self._buf = []
        return out

    def flush(self) -> str:
        sentence = "".join(self._buf).strip()
        self._buf = []
        return sentence
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/llm/test_sentence_splitter.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/llm/sentence_splitter.py tests/llm/test_sentence_splitter.py
git commit -m "feat: ストリーム→文分割(SentenceSplitter)"
```

---

### Task 9: TTSサーバ TTSクライアント

**Files:**
- Create: `kotoha/voice/tts.py`
- Test: `tests/voice/test_tts.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `async synthesize(text: str, *, session: aiohttp.ClientSession, speaker: int = 1, base_url: str = "http://localhost:50021", timeout: aiohttp.ClientTimeout = DEFAULT_TTS_TIMEOUT) -> bytes`(WAV bytes。audio_query→synthesis の 2 段。**共有 session を使い回す前提**。各リクエストに timeout 指定)
  - `async synthesize_default(text: str, *, speaker: int = 1, base_url: str = "http://localhost:50021") -> bytes`(自前 session を張る薄ラッパ。結合テスト/単発用途)

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_tts.py`:
```python
import pytest
from kotoha.voice.tts import synthesize


class _FakeResp:
    def __init__(self, *, json_data=None, read_data=None):
        self._json = json_data
        self._read = read_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self._json

    async def read(self):
        return self._read


class _FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, params=None, json=None, timeout=None):
        self.calls.append((url, params, json, timeout))
        if url.endswith("/audio_query"):
            return _FakeResp(json_data={"speedScale": 1.0, "accent_phrases": []})
        return _FakeResp(read_data=b"RIFFfakewav")


async def test_synthesize_places_query_and_body_correctly():
    sess = _FakeSession()
    wav = await synthesize("こんにちは", session=sess, speaker=3)
    assert wav == b"RIFFfakewav"

    aq_url, aq_params, aq_body, aq_to = sess.calls[0]
    assert aq_url.endswith("/audio_query")
    assert aq_params == {"text": "こんにちは", "speaker": 3}   # クエリ
    assert aq_body is None                                    # body 空
    assert aq_to is not None                                  # timeout 指定あり

    syn_url, syn_params, syn_body, syn_to = sess.calls[1]
    assert syn_url.endswith("/synthesis")
    assert syn_params == {"speaker": 3}                        # クエリ
    assert syn_body == {"speedScale": 1.0, "accent_phrases": []}  # AudioQuery が body


@pytest.mark.integration
async def test_synthesize_default_real_tts_http():
    from kotoha.voice.tts import synthesize_default

    wav = await synthesize_default("こんにちは", speaker=1)
    assert wav[:4] == b"RIFF"
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_tts.py -v -m "not integration"`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.voice.tts'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/tts.py`:
```python
import aiohttp

DEFAULT_TTS_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def synthesize(
    text: str,
    *,
    session: aiohttp.ClientSession,
    speaker: int = 1,
    base_url: str = "http://localhost:50021",
    timeout: aiohttp.ClientTimeout = DEFAULT_TTS_TIMEOUT,
) -> bytes:
    """TTSサーバ で WAV bytes を生成(既定 24kHz mono 16-bit)。共有 session 前提。"""
    # Step1: audio_query -- text/speaker はクエリ、body 空
    async with session.post(
        f"{base_url}/audio_query",
        params={"text": text, "speaker": speaker},
        timeout=timeout,
    ) as r:
        r.raise_for_status()
        query = await r.json()
    # Step2: synthesis -- speaker はクエリ、AudioQuery(round-trip)は body
    async with session.post(
        f"{base_url}/synthesis",
        params={"speaker": speaker},
        json=query,
        timeout=timeout,
    ) as r:
        r.raise_for_status()
        return await r.read()   # WAV バイナリ(read、json ではない)


async def synthesize_default(
    text: str,
    *,
    speaker: int = 1,
    base_url: str = "http://localhost:50021",
) -> bytes:
    async with aiohttp.ClientSession() as session:
        return await synthesize(
            text, session=session, speaker=speaker, base_url=base_url
        )
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_tts.py -v -m "not integration"`
Expected: PASS (1 passed, 1 deselected)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/tts.py tests/voice/test_tts.py
git commit -m "feat: TTSサーバ TTSクライアント(共有session/timeout対応)"
```

---

### Task 10: Discord再生とbarge-in制御 (FFmpegPCMAudio)

> discord 系が必要(`.[voice,dev]`)。integration テストは ffmpeg バイナリ必須。

**Files:**
- Create: `kotoha/voice/playback.py`
- Test: `tests/voice/test_playback.py`

**Interfaces:**
- Consumes: なし
- Produces: `class Player: __init__(self, voice_client, *, source_factory: Callable[[bytes], discord.AudioSource] | None = None, loop=None)`。既定 `source_factory` は `lambda wav: discord.FFmpegPCMAudio(io.BytesIO(wav), pipe=True)`。`stop(self) -> None`(再生中のみ `vc.stop()`、interrupted フラグを立てる), `async play_and_wait(self, wav_bytes: bytes) -> bool`(再生前に必ず stop→play、自然終了で True / 割り込みで False), `is_playing(self) -> bool`

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_playback.py`:
```python
import pytest
from kotoha.voice.playback import Player


class _FakeVC:
    def __init__(self):
        self.played = []
        self.stops = 0
        self._playing = False
        self._after = None
        self.fire_after_immediately = True

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return False

    def play(self, source, after=None):
        self.played.append(source)
        self._playing = True
        self._after = after
        if self.fire_after_immediately and after:
            self._playing = False
            after(None)

    def stop(self):
        self.stops += 1
        self._playing = False
        if self._after:
            cb, self._after = self._after, None
            cb(None)


async def test_play_and_wait_uses_factory_and_returns_true_on_finish():
    vc = _FakeVC()
    p = Player(vc, source_factory=lambda wav: ("SRC", wav))
    ok = await p.play_and_wait(b"WAV")
    assert ok is True
    assert vc.played == [("SRC", b"WAV")]


async def test_play_and_wait_stops_before_playing_when_busy():
    vc = _FakeVC()
    vc._playing = True
    p = Player(vc, source_factory=lambda wav: ("SRC", wav))
    await p.play_and_wait(b"WAV")
    assert vc.stops >= 1            # barge-in 安全: play 前に stop


def test_stop_only_when_playing():
    vc = _FakeVC()
    p = Player(vc, source_factory=lambda wav: ("SRC", wav))
    p.stop()
    assert vc.stops == 0
    vc._playing = True
    p.stop()
    assert vc.stops == 1


@pytest.mark.integration
def test_ffmpeg_resamples_tts_http_wav_to_discord_frame():
    import io
    import discord
    import asyncio
    from kotoha.voice.tts import synthesize_default

    wav = asyncio.run(synthesize_default("テスト", speaker=1))
    src = discord.FFmpegPCMAudio(io.BytesIO(wav), pipe=True)
    frame = src.read()
    assert len(frame) == 3840      # 20ms @ 48kHz stereo 16-bit
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_playback.py -v -m "not integration"`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.voice.playback'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/playback.py`:
```python
import asyncio
import io
from typing import Callable, Optional

import discord


def _default_source_factory(wav: bytes) -> discord.AudioSource:
    # ffmpeg が 24kHz mono を 48kHz stereo/16-bit へ自動リサンプル。
    # discord.PCMAudio は変換しないので使わない(~4倍速・早口化の地雷)。
    return discord.FFmpegPCMAudio(io.BytesIO(wav), pipe=True)


class Player:
    """Discord 再生 + barge-in。play 前に必ず stop して二重再生例外を回避。"""

    def __init__(
        self,
        voice_client,
        *,
        source_factory: Optional[Callable[[bytes], discord.AudioSource]] = None,
        loop=None,
    ):
        self._vc = voice_client
        self._source_factory = source_factory or _default_source_factory
        self._loop = loop
        self._interrupted = False

    def is_playing(self) -> bool:
        return self._vc.is_playing()

    def stop(self) -> None:
        self._interrupted = True
        if self._vc.is_playing() or self._vc.is_paused():
            self._vc.stop()

    async def play_and_wait(self, wav_bytes: bytes) -> bool:
        loop = self._loop or asyncio.get_running_loop()
        self._interrupted = False
        done = asyncio.Event()

        def _after(err):
            # 再生スレッドで呼ばれる -> ループへ marshalling
            loop.call_soon_threadsafe(done.set)

        if self._vc.is_playing() or self._vc.is_paused():
            self._vc.stop()  # barge-in 安全(同期で player クリア)
        source = self._source_factory(wav_bytes)
        self._vc.play(source, after=_after)
        await done.wait()
        return not self._interrupted
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_playback.py -v -m "not integration"`
Expected: PASS (3 passed, 1 deselected)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/playback.py tests/voice/test_playback.py
git commit -m "feat: Discord再生とbarge-in制御(FFmpegPCMAudio)"
```

---

### Task 11: オーケストレータ: 1ターン・TTS/再生パイプライン

**Files:**
- Create: `kotoha/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `SentenceSplitter`(Task 8), `persona`(Task 7), `Transcriber`(Task 5), `Player`(Task 10), `stream_chat`(Task 7), **`synthesize`(Task 9、session 束縛済みラッパとして注入。`tts: async (text)->bytes`)**
- Produces: `class Orchestrator: __init__(self, *, transcriber, llm_stream, tts, player, model: str, vad_factory, persona=<kotoha.llm.persona>, history_max_turns=20, vad_threshold=0.5, vad_silence_ms=400, bargein_trigger_ms=250, sample_rate=SAMPLE_RATE_HZ, vad_window=VAD_WINDOW_SAMPLES, fallback_text="...", stt_timeout=30.0, tts_timeout=15.0, play_timeout=60.0, splitter_factory=SentenceSplitter, loop=None)`。本タスクで実装するメソッド: `async handle_utterance(self, user_id, audio) -> None`, `async _run_turn(self, messages) -> None`(及び内部の 3 段パイプラインコルーチン `_llm_to_sentences` / `_sentences_to_audio` / `_audio_to_playback` と `_speak_fallback`)。属性 `self.history: collections.deque`。
  - `transcriber`: `.transcribe(audio) -> str`(同期、executor + wait_for で実行)
  - `llm_stream`: `async (messages, *, model) -> AsyncIterator[str]`
  - `tts`: `async (text) -> bytes`(bot 側で `functools.partial(synthesize, session=...)` を注入)
  - `player`: `Player` 互換(`is_playing()`, `stop()`, `async play_and_wait(wav)->bool`)
  - **`vad_factory`: `Callable[[], SileroVad]`**(呼ぶたびにステートフルな新規 VAD を生成。`.prob(frame)->float` と `.reset()` を持つ。Task 12 で使用)

> **設計変更(点1/11/22)**: 以前の `vad`(単一ステートフルインスタンス共有)を廃し、`vad_factory` を受け取る。ユーザー別・用途別に独立した silero ストリームを生成する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_orchestrator.py`:
```python
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
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'kotoha.orchestrator'`)

- [ ] **Step 3: 最小実装**

`kotoha/orchestrator.py`:
```python
import asyncio
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np

from kotoha.config import SAMPLE_RATE_HZ, VAD_WINDOW_SAMPLES
from kotoha.llm import persona as _persona
from kotoha.llm.sentence_splitter import SentenceSplitter
# Task 12 で feed_audio から使用
from kotoha.voice.vad import VadSegmenter, BargeInDetector

logger = logging.getLogger(__name__)

_SENTINEL = object()


def make_on_audio(orch):
    """受信スレッド -> Orchestrator.feed_audio の薄い配線(単体テスト可能)。"""
    def on_audio(user_id, audio):
        orch.feed_audio(user_id, audio)
    return on_audio


class Orchestrator:
    """受信→STT→LLM→文分割→TTS→再生の中央配線。

    TTS 合成と再生を 3 段の asyncio キュー(文 -> 音声 -> 再生)で
    パイプライン化し、LLM 消費を止めずに TTS と再生を重ねる。
    """

    def __init__(
        self,
        *,
        transcriber,
        llm_stream,
        tts,
        player,
        model: str,
        vad_factory,
        persona=_persona,
        history_max_turns: int = 20,
        vad_threshold: float = 0.5,
        vad_silence_ms: int = 400,
        bargein_trigger_ms: int = 250,
        sample_rate: int = SAMPLE_RATE_HZ,
        vad_window: int = VAD_WINDOW_SAMPLES,
        fallback_text: str = "ごめん、うまく聞き取れなかった。",
        stt_timeout: float = 30.0,
        tts_timeout: float = 15.0,
        play_timeout: float = 60.0,
        splitter_factory=SentenceSplitter,
        loop=None,
    ):
        self.transcriber = transcriber
        self.llm_stream = llm_stream
        self.tts = tts
        self.player = player
        self.model = model
        self.vad_factory = vad_factory          # Callable[[], SileroVad]
        self.persona = persona
        self.history: deque = deque(maxlen=history_max_turns * 2)
        self.vad_threshold = vad_threshold
        self.vad_silence_ms = vad_silence_ms
        self.bargein_trigger_ms = bargein_trigger_ms
        self.sample_rate = sample_rate
        self.vad_window = vad_window
        self.fallback_text = fallback_text
        self._stt_timeout = stt_timeout
        self._tts_timeout = tts_timeout
        self._play_timeout = play_timeout
        self.splitter_factory = splitter_factory
        self._loop = loop
        self._turn_task: Optional[asyncio.Task] = None
        self._assistant_buf = ""
        # --- Task 12 で使用する状態 ---
        self._last_speaker: Optional[int] = None
        self._segmenters: dict = {}
        self._bargein_detectors: dict = {}
        self._pending_preroll: dict = {}
        self._sentence_q: Optional[asyncio.Queue] = None
        self._play_q: Optional[asyncio.Queue] = None
        # VAD 推論をループ外へ逃がす単一ワーカースレッド(点12)
        self._vad_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vad")

    # ---- ターンの保存/差し替え ----
    def _save_partial(self) -> None:
        # 中断時点までの bot 発話を履歴へ。冪等(buf を毎回クリア)。
        if self._assistant_buf.strip():
            self.history.append(
                {"role": "assistant", "content": self._assistant_buf.strip()}
            )
        self._assistant_buf = ""

    def _flush_play_queue(self) -> None:
        # barge-in (c): TTS/再生キューをフラッシュ
        for q in (self._sentence_q, self._play_q):
            if q is None:
                continue
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break

    def _preempt_turn(self) -> None:
        # 進行中ターンを差し替える前に、中断時点までの bot 発話を退避(点10)。
        self._save_partial()
        self._flush_play_queue()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()

    async def handle_utterance(self, user_id: int, audio: np.ndarray) -> None:
        self._preempt_turn()    # 進行中ターンがあれば partial 保存してから cancel(点10)
        loop = asyncio.get_running_loop()
        self._loop = loop
        # STT: executor で実行し wait_for で上限(点5)。例外は沈黙扱い(点4)。
        try:
            text = await asyncio.wait_for(
                loop.run_in_executor(None, self.transcriber.transcribe, audio),
                timeout=self._stt_timeout,
            )
        except Exception:
            logger.exception("STT failed (user=%s) -> 沈黙扱いでスキップ", user_id)
            return
        text = (text or "").strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})
        messages = self.persona.build_messages(list(self.history))
        self._turn_task = asyncio.create_task(self._run_turn(messages))
        try:
            await self._turn_task
        except asyncio.CancelledError:
            pass

    async def _run_turn(self, messages: list[dict]) -> None:
        splitter = self.splitter_factory()
        self._assistant_buf = ""
        self._sentence_q = asyncio.Queue()
        self._play_q = asyncio.Queue()
        tasks = [
            asyncio.create_task(self._llm_to_sentences(messages, splitter)),
            asyncio.create_task(self._sentences_to_audio()),
            asyncio.create_task(self._audio_to_playback()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise
        except Exception:
            # LLM/TTS/API/再生失敗 -> ログ + フォールバック発話(点3)
            logger.exception("ターン処理に失敗 -> フォールバック発話")
            for t in tasks:
                t.cancel()
            await self._speak_fallback()
        finally:
            self._save_partial()
            self._sentence_q = None
            self._play_q = None

    async def _llm_to_sentences(self, messages, splitter) -> None:
        # LLM 消費は TTS/再生を待たずに進む(キューへ流すだけ)。
        async for piece in self.llm_stream(messages, model=self.model):
            self._assistant_buf += piece
            for sentence in splitter.push(piece):
                await self._sentence_q.put(sentence)
        tail = splitter.flush()
        if tail:
            await self._sentence_q.put(tail)
        await self._sentence_q.put(_SENTINEL)

    async def _sentences_to_audio(self) -> None:
        # 再生中の文と並行して次文を合成(パイプライン化)。
        while True:
            sentence = await self._sentence_q.get()
            if sentence is _SENTINEL:
                await self._play_q.put(_SENTINEL)
                return
            wav = await asyncio.wait_for(self.tts(sentence), timeout=self._tts_timeout)
            await self._play_q.put(wav)

    async def _audio_to_playback(self) -> None:
        while True:
            wav = await self._play_q.get()
            if wav is _SENTINEL:
                return
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )

    async def _speak_fallback(self) -> None:
        try:
            wav = await asyncio.wait_for(
                self.tts(self.fallback_text), timeout=self._tts_timeout
            )
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )
        except Exception:
            logger.exception("フォールバック発話にも失敗")
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: オーケストレータの1ターン・TTS/再生パイプライン(エラー処理/timeout/fallback)"
```

---

### Task 12: オーケストレータ: barge-in連携・音声ルーティング・bot配線

**Files:**
- Modify: `kotoha/orchestrator.py`(`request_bargein` / `feed_audio` / `_route_audio` / VAD 生成ヘルパを追記)
- Create: `kotoha/health.py`(起動時の疎通チェック)
- Create: `kotoha/bot.py`(Discord 接続のエントリポイント。手動/結合確認用)
- Test: `tests/test_bargein.py`
- Test: `tests/test_health.py`
- Test: `tests/test_wiring.py`

**Interfaces:**
- Consumes: `VadSegmenter`, `BargeInDetector`(Task 3/4)、`PerUserSink`(Task 6)、`SileroVad`(Task 3)、`synthesize`/`stream_chat`(Task 7/9)、Task 11 の `Orchestrator`
- Produces:
  - `Orchestrator.request_bargein(self, user_id: Optional[int] = None) -> None`((b) LLM タスク cancel + (a) `player.stop()` + (c) TTS/再生キューフラッシュ + 中断時点までの bot 発話保存 + 割り込みユーザーの pre-roll をセグメンタへ引き継ぎ + 全 VAD ストリーム reset)
  - `Orchestrator.feed_audio(self, user_id, audio) -> None`(受信スレッドから threadsafe。VAD 推論を専用ワーカースレッドへ submit)
  - `Orchestrator._route_audio(self, user_id, audio) -> None`(ワーカースレッド側の同期ルーティング。再生中はユーザー別 `BargeInDetector`、待機中はユーザー別 `VadSegmenter`。確定イベントだけ `call_soon_threadsafe` でループへ)
  - `make_on_audio(orch)`(Task 11 で実装済み)
  - `health.check_services(session, *, ollama_url, tts_http_url) -> dict[str, bool]`
  - `bot.run_bot(token: str, channel_id: int, config: Config) -> None`(同期エントリ。共有 session 生成→疎通チェック→Discord 接続→`vc.listen(PerUserSink(make_on_audio(orch)))`)

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_bargein.py`:
```python
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
```

`tests/test_health.py`:
```python
from kotoha.health import check_services


class _Resp:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _OkSession:
    def get(self, url):
        return _Resp(200)


class _BadSession:
    def get(self, url):
        raise RuntimeError("conn refused")


async def test_check_services_all_ok():
    res = await check_services(_OkSession(), ollama_url="http://o", tts_http_url="http://v")
    assert res == {"ollama": True, "tts_http": True}


async def test_check_services_marks_down_on_error():
    res = await check_services(_BadSession(), ollama_url="http://o", tts_http_url="http://v")
    assert res == {"ollama": False, "tts_http": False}
```

`tests/test_wiring.py`:
```python
from kotoha.orchestrator import make_on_audio


def test_make_on_audio_forwards_to_feed_audio():
    calls = []

    class _O:
        def feed_audio(self, uid, audio):
            calls.append((uid, audio))

    on_audio = make_on_audio(_O())
    on_audio(5, "AUDIO")
    assert calls == [(5, "AUDIO")]
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_bargein.py tests/test_health.py tests/test_wiring.py -v`
Expected: FAIL (`AttributeError: 'Orchestrator' object has no attribute 'request_bargein'` ほか)
> `make_on_audio` は Task 11 で実装済みなので `tests/test_wiring.py` は先に緑になりうる。

- [ ] **Step 3: 最小実装**

`kotoha/orchestrator.py` の `Orchestrator` にメソッドを追記:
```python
    # ---- VAD ストリーム生成(ユーザー別・用途別に独立した silero を持つ) ----
    def _get_segmenter(self, user_id: int) -> VadSegmenter:
        seg = self._segmenters.get(user_id)
        if seg is None:
            vad = self.vad_factory()   # 新規ステートフル VAD
            seg = VadSegmenter(
                vad.prob, reset_fn=vad.reset,
                threshold=self.vad_threshold, silence_ms=self.vad_silence_ms,
                sample_rate=self.sample_rate, window=self.vad_window,
            )
            self._segmenters[user_id] = seg
        return seg

    def _get_bargein_detector(self, user_id: int) -> BargeInDetector:
        det = self._bargein_detectors.get(user_id)
        if det is None:
            vad = self.vad_factory()   # セグメンタとは別の独立ストリーム
            det = BargeInDetector(
                vad.prob, reset_fn=vad.reset,
                threshold=self.vad_threshold, trigger_ms=self.bargein_trigger_ms,
                sample_rate=self.sample_rate, window=self.vad_window,
            )
            self._bargein_detectors[user_id] = det
        return det

    def _reset_all_vad(self) -> None:
        for s in self._segmenters.values():
            s.reset()
        for d in self._bargein_detectors.values():
            d.reset()

    def _spawn_turn(self, user_id: int, utterance: np.ndarray) -> None:
        task = asyncio.ensure_future(self.handle_utterance(user_id, utterance))
        task.add_done_callback(self._log_task_exception)   # 未捕捉例外を握り潰さない(点4)

    @staticmethod
    def _log_task_exception(task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("utterance task failed", exc_info=exc)

    # ---- barge-in ----
    def request_bargein(self, user_id: Optional[int] = None) -> None:
        # 中断時点までの bot 発話を保存 (§4) -> (c)キューフラッシュ -> (b)LLM中断 -> (a)再生停止
        self._save_partial()
        self._flush_play_queue()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        self.player.stop()
        # 割り込みユーザーの冒頭(pre-roll)を次のセグメンタへ引き継ぐ(点9)
        if user_id is not None:
            det = self._bargein_detectors.get(user_id)
            if det is not None:
                self._pending_preroll[user_id] = det.drain()
        # idle<->再生中のストリーム切替なので全 VAD 状態をリセット(点1/11/16)
        self._reset_all_vad()

    # ---- 音声ルーティング ----
    def feed_audio(self, user_id: int, audio: np.ndarray) -> None:
        # 受信スレッドから安全に呼べる。torch VAD 推論を専用ワーカースレッドへ
        # 逃がし、受信スレッドもイベントループもブロックしない(点12)。
        self._vad_executor.submit(
            self._route_audio, user_id, np.asarray(audio, dtype=np.float32)
        )

    def _route_audio(self, user_id: int, audio: np.ndarray) -> None:
        # VAD ワーカースレッド(単一)で実行 -> 確定イベントだけループへ marshalling。
        try:
            if self.player.is_playing():
                det = self._get_bargein_detector(user_id)
                if det.push(audio):
                    self._loop.call_soon_threadsafe(self.request_bargein, user_id)
            else:
                seg = self._get_segmenter(user_id)
                pre = self._pending_preroll.pop(user_id, None)
                if pre is not None and len(pre):
                    audio = np.concatenate([pre, audio])   # 割り込み冒頭を欠落させない
                for utterance in seg.push(audio):
                    self._last_speaker = user_id
                    self._loop.call_soon_threadsafe(
                        self._spawn_turn, user_id, utterance
                    )
        except Exception:
            logger.exception("VAD routing failed (user=%s)", user_id)
```

`kotoha/health.py`:
```python
import logging

logger = logging.getLogger(__name__)


async def check_services(session, *, ollama_url: str, tts_http_url: str) -> dict:
    """起動時の最小疎通チェック。プロセス再起動・常時ウォッチドッグはフェーズ1.x。"""
    results = {}
    for name, url in (("ollama", f"{ollama_url}/api/tags"),
                      ("tts_http", f"{tts_http_url}/version")):
        try:
            async with session.get(url) as r:
                results[name] = r.status == 200
        except Exception:
            logger.warning("%s への疎通に失敗: %s", name, url)
            results[name] = False
    return results
```

`kotoha/bot.py`(手動/結合確認用エントリ。単体テスト対象外):
```python
import asyncio
import functools
import logging

import aiohttp
import discord
from discord.ext import voice_recv

from kotoha.config import Config
from kotoha.health import check_services
from kotoha.llm.front_client import stream_chat
from kotoha.orchestrator import Orchestrator, make_on_audio
from kotoha.voice.playback import Player
from kotoha.voice.receiver import PerUserSink
from kotoha.voice.stt import Transcriber, build_whisper
from kotoha.voice.tts import synthesize
from kotoha.voice.vad import SileroVad

logger = logging.getLogger(__name__)


def run_bot(token: str, channel_id: int, config: Config) -> None:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        loop = asyncio.get_running_loop()
        # 長命の共有 session(llm / tts_http 兼用)。文ごとに接続を張り直さない(点14)。
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_read=300)
        )
        # 起動時の死活疎通チェック(設計書 §4、点6)
        health = await check_services(
            session, ollama_url=config.ollama_url, tts_http_url=config.tts_http_url
        )
        for name, ok in health.items():
            if not ok:
                logger.warning("%s に接続できません(起動は継続)", name)

        channel = client.get_channel(channel_id)
        vc = await channel.connect(cls=voice_recv.VoiceRecvClient)  # 受信に必須

        transcriber = Transcriber(
            build_whisper(
                config.whisper_model,
                device=config.whisper_device,
                compute_type=config.whisper_compute_type,
            ),
            language=config.language,
        )
        orch = Orchestrator(
            transcriber=transcriber,
            # llm/tts は共有 session を束縛して I/F に合わせる
            llm_stream=functools.partial(
                stream_chat, base_url=config.ollama_url, session=session
            ),
            tts=functools.partial(           # async (text)->bytes(点14/23)
                synthesize,
                session=session,
                speaker=config.tts_http_speaker,
                base_url=config.tts_http_url,
            ),
            player=Player(vc, loop=loop),
            model=config.ollama_model,
            vad_factory=SileroVad,           # ユーザー別・用途別に新規生成(状態分離; 点1/11/22)
            history_max_turns=config.history_max_turns,
            vad_threshold=config.vad_threshold,
            vad_silence_ms=config.vad_silence_ms,
            bargein_trigger_ms=config.bargein_trigger_ms,
            fallback_text=config.fallback_text,
            stt_timeout=config.stt_timeout_s,
            tts_timeout=config.tts_timeout_s,
            play_timeout=config.play_timeout_s,
            loop=loop,
        )
        # 受信スレッド -> threadsafe な feed_audio(内部で VAD ワーカースレッドへ submit)
        vc.listen(PerUserSink(make_on_audio(orch)))  # await 不要

    client.run(token)
```

> 配線の不変条件(点19/24): VadSegmenter/BargeInDetector の `sample_rate`/`window` は `Config` 由来の `SAMPLE_RATE_HZ`/`VAD_WINDOW_SAMPLES`(Orchestrator のデフォルト)を単一の真実源として渡す。`make_on_audio` の受信スレッド→`feed_audio` 配線は `tests/test_wiring.py` で単体検証する。

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_bargein.py tests/test_health.py tests/test_wiring.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/orchestrator.py kotoha/health.py kotoha/bot.py tests/test_bargein.py tests/test_health.py tests/test_wiring.py
git commit -m "feat: barge-in連携・VAD状態分離・音声ルーティング・bot配線・疎通チェック"
```

---

## フェーズ1完了確認(全体スモーク)

- [ ] 単体テスト一括: `python -m pytest -m "not integration" -v`(全タスクの単体テストが PASS)
- [ ] 結合テスト(要 Ollama / TTSサーバ / ffmpeg / GPU): `python -m pytest -m integration -v`
  - 事前に: `python -m pip install -e ".[all,dev]" --pre`、`ollama serve` + `ollama pull qwen2.5:7b-instruct`、`docker run --rm -p 50021:50021 tts_http/tts_http_engine:cpu-latest`、`brew install ffmpeg`(または apt)
  - 重点: 実 silero-vad での `SileroVad.prob` 形状/値域(Task 3 integration)。
- [ ] 実 VC 手動確認(設計書 §10): `python -c "from kotoha.bot import run_bot; from kotoha.config import Config; run_bot('<TOKEN>', <CHANNEL_ID>, Config())"` で VC に参加し、
  - (a) 往復の低遅延(2 文目以降に無音ギャップが出ないこと=TTS/再生パイプライン)
  - (b) 発話で割り込み(barge-in)→即停止 + 割り込み冒頭が取りこぼされず応答
  - (c) 複数人で最後の話者へ応答
  - (d) Ollama/TTSサーバ を一時停止してフォールバック発話・沈黙スキップが効くこと
  - bot 配線(`make_on_audio`→`feed_audio`、VAD ワーカースレッド非ブロック、`SileroVad` per-stream)の体感確認

---

## Self-Review(スペック対応表 §4 / 型整合 / プレースホルダ確認)

**§4 データフロー網羅:**
- データフロー1(ユーザー別 20ms PCM 供給): Task 6 `PerUserSink`(wants_opus False / write 同期 / None スキップ / super().__init__)。
- データフロー2(Silero VAD で発話開始/終了、無音 ~400ms 区切り): Task 3 `SileroVad`(512 samples float32, stateful, reset)+ `VadSegmenter`(silence_ms=400、区間確定で reset)。
- データフロー3(faster-whisper で区間文字起こし + 話者ID): Task 5 `Transcriber` + Task 12 `_route_audio` が `user_id` 付きで `handle_utterance` 起動。**話者IDの扱い(点7)**: フェーズ1では話者IDは「応答先選択(=最後の話者へ応答)」にのみ使い、テキスト本文/履歴 content には付与しない方針を明記(LLM への話者ラベル注入はフェーズ1.5)。
- データフロー4(履歴追加→フロント LLM ストリーミング): Task 7 `stream_chat` / `persona.build_messages` + Task 11 `handle_utterance`。
- データフロー5(文単位で確定ごとに TTSサーバ 合成→再生、**パイプライン化**): Task 8 `SentenceSplitter` + Task 9 `synthesize`(session束縛) + Task 11 の 3 段 asyncio キュー(`_llm_to_sentences`→`_sentences_to_audio`→`_audio_to_playback`)。LLM 消費は TTS/再生を待たず進み、再生中に次文を合成する真のパイプライン(点2 修正)。
- データフロー6(順次再生): Task 10 `Player.play_and_wait` + Task 11 `_audio_to_playback`(キュー順)。
- barge-in (a)再生停止 (b)LLM 中断 (c)**TTS/再生キューフラッシュ** / ~250ms 継続検出: Task 4 `BargeInDetector`(trigger_ms=250)+ Task 12 `request_bargein`(`_flush_play_queue` で c を実装)/`_route_audio`。
- barge-in「中断時点までの bot 発話は履歴に残す」: `request_bargein` と `_preempt_turn`(handle_utterance 経由の差し替え)双方で `_save_partial`(冪等)を呼ぶ(点10 修正)。割り込み冒頭の pre-roll を `drain`→`_pending_preroll`→セグメンタへ引き継ぎ(点9 修正)。
- 複数話者「受信はユーザー別」「最後に発話したユーザーへ応答」: Task 6 ユーザー別 + Task 12 ユーザー別 segmenter/detector。`_last_speaker` は `_route_audio` で確定区間ごとに更新し応答先を表す(実際の「最後の話者優先」は後発 utterance が `_preempt_turn` で先行ターンを差し替える挙動で実現することを明記; 点8)。
- **エラー処理(§4)**: STT 失敗→try/except で沈黙スキップ + 空テキストスキップ(点4); LLM/TTS/API/再生失敗→ログ + フォールバック発話(`_speak_fallback`, 点3); 各段タイムアウト `stt/tts/play_timeout`(点5); 死活監視→起動時 `health.check_services`(点6、再起動はフェーズ1.x へ延期と明記)。`_spawn_turn` の ensure_future には `add_done_callback` で未捕捉例外をログ(点4)。

**VAD ステートフル契約(高severity 1/11/16/22)の整合:**
- 単一共有インスタンスを廃止し `vad_factory` 契約へ変更。ユーザー別・用途別(segmenter/bargein)に独立 `SileroVad` を生成し、LSTM 状態の混線を排除。発話区間確定(`VadSegmenter.reset_fn`)・barge-in/ストリーム切替(`request_bargein`→`_reset_all_vad`)で `reset_states()` を呼ぶ配線を追加。`_CountingVad` で reset 呼び出しとインスタンス分離を単体検証、実モデルは Task 3 integration で形状/値域を検証。
- VAD 推論は専用ワーカースレッド(`ThreadPoolExecutor(max_workers=1)`)へ offload し、イベントループ(Ollama ストリーム/再生)をブロックしない(点12)。

**型整合(Interfaces/Produces/Consumes):**
- `tts` 契約は `async (text)->bytes`。Task 11 Consumes を `synthesize`(Task 9、`functools.partial(synthesize, session=...)` で session 束縛)に統一(点14/23 修正)。`synthesize_default` は結合/単発用途のみ。
- `vad_factory: Callable[[], SileroVad]`(`.prob(frame)->float`, `.reset()`)。bot は `vad_factory=SileroVad` を渡し、テストは `lambda: _CountingVad([...])`/`lambda: _FakeVad()`。`_FakeVad`/`_CountingVad` に `.reset()` を実装し契約一致。
- `VadSegmenter`/`BargeInDetector` に `reset_fn`/`drain` を追加し、`sample_rate`/`window` は Config 由来定数を Orchestrator から明示注入(点24)。

**その他:**
- 音声内部表現 16kHz/mono/float32 統一: Task 2 を全段が経由。線形補間=アンチエイリアスなしをコメント明記(点13)。
- 地雷回避: FFmpegPCMAudio(PCMAudio 不使用)/silero 512 samples 厳守(端数破棄)/TTSサーバ クエリ vs ボディ位置/Ollama NDJSON ネスト `message.content`/接続クローズで生成停止。
- 依存の段階導入(点17/18): base=aiohttp+numpy、extra=voice/ml/dev/all。Task 1 は pytest だけで赤→緑、重い ML は Task 3 以降で導入。bootstrap ステップ追加で最初の赤理由を `kotoha` 未作成に固定。
- commit 粒度(点20): Task 7 は persona/front_client を別 commit に分割。
- テストのフレーキー回避(点21): `test_request_bargein_*` を `sleep` から `first_play`/`reached` の `asyncio.Event` 同期点へ変更。
- bot 配線テスト(点19): `make_on_audio` を純関数化し `tests/test_wiring.py` で単体検証。

**プレースホルダ確認:** 各 Task の Files/Interfaces/コード/コミットを完備。未実装の TODO・`...` プレースホルダは残していない(死活監視のプロセス再起動のみ明示的にフェーズ1.x へ延期と注記)。

> スコープ外(本計画に含めない): §5 ターンテイキング・相槌(フェーズ1.5)、§6 ディスパッチ・プロトコル以降、`tone_adjuster.py`、`turntaking/`、`dispatch/`、`handlers/`。死活監視のうちプロセス再起動・常時ウォッチドッグはフェーズ1.x(本フェーズは起動時疎通チェックのみ)。話者ラベルの LLM 文脈注入はフェーズ1.5。アンチエイリアス付きリサンプラ置換は品質要件が出た段階で。
