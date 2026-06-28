# 画面知覚 Phase 1 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** つくよみが画面を一定間隔でキャプチャし、ローカル VLM で要約して会話へ織り込む知覚機能を、既存の音声ループを止めずに追加する。

**Architecture:** 新規 `kotoha/screen/` に背景キャプチャ→VLM→要約保持のループを置き、`ScreenContext` を介して orchestrator が最新要約を毎ターン system メッセージへ注入する。会話 LLM とそれ以外（知覚 VLM・記憶圧縮・関係性分析）を base_url で別バックエンドへ振り分け、4080(CUDA・会話) と Radeon VII(Vulkan・非リアルタイム) に分離する。ゲーム起動を検知して省力型／リアルタイム型へ切り替える。

**Tech Stack:** Python 3.11+, asyncio, aiohttp, mss(MIT), Pillow(MIT-CMU), dxcam-cpp(MIT, Windows), ローカル VLM は Qwen3-VL-4B(Apache-2.0) を Ollama または OpenAI 互換サーバ(llama.cpp Vulkan) 経由で呼ぶ。

設計の正は [docs/specs/2026-06-28-screen-perception-design.md](../specs/2026-06-28-screen-perception-design.md)。

## Global Constraints

- Python は `>=3.11`。新規依存は permissive ライセンスのみ（mss=MIT, Pillow=MIT-CMU, dxcam-cpp=MIT）。
- 画面知覚は既定 OFF のオプトイン（`screen_perception_enabled: bool = False`）。
- スクリーンショットはディスクへ保存しない。メモリ上で扱い、VLM へ渡したら破棄する。`ScreenContext` が保持するのは短い要約テキストのみ。
- 知覚は best-effort。キャプチャ失敗・VLM 接続不可・タイムアウトでも会話ループを絶対に止めない。
- 本体はバックエンド非依存。推論先は base_url で切り替える。`vlm_perception_url` と `aux_llm_url` は空文字なら `ollama_url` へフォールバックする。
- ユニットテストは GPU・外部サービス・画面ハードなしで通す（fake 注入）。実機要は `@pytest.mark.integration` ＋ テスト内 `pytest.importorskip`。既定実行は `-m "not integration"`。
- 重い依存（mss/dxcam/PIL）は関数・メソッド内で遅延 import する（`sounddevice` を `speaker.py`/`mic.py` が遅延 import する既存の流儀に合わせる）。
- コミットは Conventional Commits。タイトルは英語。末尾に空行＋`Co-Authored-By: Claude <noreply@anthropic.com>`。

---

### Task 1: 設定フィールドの追加

**Files:**
- Modify: `kotoha/config.py`（`Config` dataclass の末尾に追記）
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` に画面知覚・ルーティング用フィールド（下記の名前と型）。後続タスクがこれを参照する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py` に追記。

```python
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
    assert c.vlm_perception_model == "qwen3-vl:4b"
    assert c.vlm_perception_api == "openai"
    assert c.vlm_perception_timeout_s == 20.0
    assert "画面" in c.vlm_perception_prompt
    assert c.aux_llm_url == ""
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_config.py::test_screen_perception_defaults -v`
Expected: FAIL（`AttributeError: ... has no attribute 'screen_perception_enabled'`）

- [ ] **Step 3: 実装する**

`kotoha/config.py` の `Config` dataclass の `memory_short_term_max` 行の直後に追記。

```python
    # --- 画面知覚 (docs/specs/2026-06-28-screen-perception-design.md) ---
    screen_perception_enabled: bool = False        # 既定OFFのオプトイン
    screen_capture_backend: str = "mss"            # "mss" | "dxcam"(Windows・ゲーム)
    screen_capture_max_long_edge: int = 1024       # 送信前の縮小上限(長辺px)
    screen_normal_interval_s: float = 4.0          # 通常モードのキャプチャ間隔
    screen_game_mode: str = "powersave"            # "powersave" | "realtime"
    screen_game_realtime_interval_s: float = 0.5   # リアルタイム型の間隔
    screen_summary_max_age_s: float = 30.0         # これより古い要約は会話へ注入しない
    screen_game_detect_fullscreen: bool = True     # 前面窓フルスクリーン検知
    screen_game_process_names: tuple = ()          # 補正用のプロセス名リスト
    screen_game_poll_s: float = 2.0                # ゲーム検出のポーリング間隔
    vlm_perception_url: str = ""                   # 知覚VLM のURL。空なら ollama_url
    vlm_perception_model: str = "qwen3-vl:4b"
    vlm_perception_api: str = "openai"             # "openai" | "ollama"
    vlm_perception_timeout_s: float = 20.0
    vlm_perception_prompt: str = (
        "次の画面のスクリーンショットを見て、いま何が映っているかを日本語で1〜2文、"
        "簡潔に説明して。固有名詞やUIの文字があれば拾う。推測は最小限に。"
    )
    aux_llm_url: str = ""                           # 非リアルタイムLLM のURL。空なら ollama_url
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/config.py tests/test_config.py
git commit -m "feat(config): add screen perception and aux-endpoint settings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: ScreenContext（最新要約とモードの保持）

**Files:**
- Create: `kotoha/screen/__init__.py`
- Create: `kotoha/screen/state.py`
- Test: `tests/screen/__init__.py`, `tests/screen/test_state.py`

**Interfaces:**
- Produces: `ScreenContext(*, summary_max_age_s=30.0, clock=time.monotonic)`。メソッド `set_summary(text)`, `get_summary() -> str | None`, `set_mode(mode)`, プロパティ `mode -> str`, `background_llm_allowed() -> bool`。モード文字列は `"normal" | "game_powersave" | "game_realtime"`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/__init__.py` は空ファイル。`tests/screen/test_state.py`:

```python
from kotoha.screen.state import ScreenContext


class _Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def test_summary_roundtrip_and_staleness():
    clk = _Clock()
    ctx = ScreenContext(summary_max_age_s=10.0, clock=clk)
    assert ctx.get_summary() is None          # 未設定は None
    ctx.set_summary("  画面にエディタが映っている。 ")
    assert ctx.get_summary() == "画面にエディタが映っている。"   # strip 済み
    clk.t += 5.0
    assert ctx.get_summary() == "画面にエディタが映っている。"   # 期限内
    clk.t += 6.0
    assert ctx.get_summary() is None          # 期限切れ


def test_empty_summary_is_none():
    ctx = ScreenContext(clock=_Clock())
    ctx.set_summary("   ")
    assert ctx.get_summary() is None


def test_mode_and_background_gate():
    ctx = ScreenContext(clock=_Clock())
    assert ctx.mode == "normal"
    assert ctx.background_llm_allowed() is True
    ctx.set_mode("game_powersave")
    assert ctx.mode == "game_powersave"
    assert ctx.background_llm_allowed() is False
    ctx.set_mode("game_realtime")
    assert ctx.background_llm_allowed() is True
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_state.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.screen`）

- [ ] **Step 3: 実装する**

`kotoha/screen/__init__.py` は空ファイル。`kotoha/screen/state.py`:

```python
"""画面知覚の共有状態。最新の画面要約と現在モードをスレッドセーフに保持する。

背景の知覚ループ(書き手)と orchestrator の会話ターン(読み手)を疎結合にする。
モードは "normal" | "game_powersave" | "game_realtime"。
"""

import threading
import time


class ScreenContext:
    def __init__(self, *, summary_max_age_s: float = 30.0, clock=time.monotonic):
        self._max_age = summary_max_age_s
        self._clock = clock
        self._lock = threading.Lock()
        self._summary = ""
        self._ts = None
        self._mode = "normal"

    def set_summary(self, text: str) -> None:
        with self._lock:
            self._summary = (text or "").strip()
            self._ts = self._clock()

    def get_summary(self) -> str | None:
        """有効な最新要約。未設定・空・期限切れは None。"""
        with self._lock:
            if not self._summary or self._ts is None:
                return None
            if (self._clock() - self._ts) > self._max_age:
                return None
            return self._summary

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def background_llm_allowed(self) -> bool:
        """省力型ゲームモード中は会話以外のLLM処理を止める。"""
        return self.mode != "game_powersave"
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_state.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/__init__.py kotoha/screen/state.py tests/screen/__init__.py tests/screen/test_state.py
git commit -m "feat(screen): add ScreenContext for summary and mode state

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: ゲーム判定（純ロジック）

**Files:**
- Create: `kotoha/screen/detector.py`
- Test: `tests/screen/test_detector.py`

**Interfaces:**
- Produces: `is_game_active(foreground, *, detect_fullscreen, process_names) -> bool`。`foreground` は `{"fullscreen": bool, "process": str}` または `None`。`resolve_mode(is_game: bool, game_mode: str) -> str`（`"normal" | "game_powersave" | "game_realtime"`）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_detector.py`:

```python
from kotoha.screen.detector import is_game_active, resolve_mode


def test_none_foreground_is_not_game():
    assert is_game_active(None, detect_fullscreen=True, process_names=()) is False


def test_fullscreen_only():
    fg = {"fullscreen": True, "process": "vlc.exe"}
    assert is_game_active(fg, detect_fullscreen=True, process_names=()) is True
    assert is_game_active(fg, detect_fullscreen=False, process_names=()) is False


def test_process_list_matches_substring_case_insensitive():
    fg = {"fullscreen": False, "process": "C:/Games/EldenRing.exe"}
    assert is_game_active(fg, detect_fullscreen=False, process_names=("eldenring",)) is True
    assert is_game_active(fg, detect_fullscreen=False, process_names=("doom",)) is False


def test_resolve_mode():
    assert resolve_mode(False, "powersave") == "normal"
    assert resolve_mode(True, "powersave") == "game_powersave"
    assert resolve_mode(True, "realtime") == "game_realtime"
    assert resolve_mode(True, "anything-else") == "game_powersave"  # 既定は省力型
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_detector.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 実装する**

`kotoha/screen/detector.py`:

```python
"""ゲーム起動の判定。前面窓のフルスクリーン検知とプロセス名リストを併用する。

判定本体は純関数。前面窓情報の取得だけ OS 依存(get_foreground_info)で、注入で渡す。
"""

import logging

logger = logging.getLogger(__name__)


def is_game_active(foreground, *, detect_fullscreen: bool, process_names) -> bool:
    """foreground={"fullscreen": bool, "process": str} か None。"""
    if not foreground:
        return False
    name = (foreground.get("process") or "").lower()
    names = tuple(n.lower() for n in (process_names or ()))
    if names and name and any(n in name for n in names):
        return True
    if detect_fullscreen and foreground.get("fullscreen"):
        return True
    return False


def resolve_mode(is_game: bool, game_mode: str) -> str:
    """ゲーム判定と設定から現在モードを決める。"""
    if not is_game:
        return "normal"
    return "game_realtime" if game_mode == "realtime" else "game_powersave"
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_detector.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/detector.py tests/screen/test_detector.py
git commit -m "feat(screen): add pure game-detection and mode resolution

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: キャプチャ（縮小・エンコードの純関数＋キャプチャ実装）

**Files:**
- Modify: `pyproject.toml`（`[project.optional-dependencies]` に `screen` extra を追加、`all` を更新）
- Create: `kotoha/screen/capture.py`
- Test: `tests/screen/test_capture.py`

**Interfaces:**
- Produces: `encode_frame(image, *, max_long_edge=1024, quality=70) -> str`（PIL.Image を縮小し JPEG base64 文字列にする。プレフィックスなし）。`MssCapturer(*, max_long_edge=1024)` と `DxcamCapturer(*, max_long_edge=1024)`。両者 `capture() -> str | None`（base64 JPEG、失敗・新フレーム無しは None）。

- [ ] **Step 1: 依存 extra を追加**

`pyproject.toml` の `[project.optional-dependencies]` に追記し、`all` を更新。

```toml
screen = [
    "mss>=9.0",
    "Pillow>=10.0",
    "dxcam-cpp>=0.0.5; platform_system == 'Windows'",
]
all = ["kotoha[voice,ml,local,screen]"]
```

インストール（テスト実行環境）。

```bash
pip install -e ".[screen]"
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/screen/test_capture.py`:

```python
import base64
import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from kotoha.screen.capture import encode_frame  # noqa: E402


def test_encode_frame_downscales_and_is_valid_jpeg():
    src = Image.new("RGB", (2000, 1000), (10, 20, 30))
    b64 = encode_frame(src, max_long_edge=1024)
    assert isinstance(b64, str) and b64
    raw = base64.b64decode(b64)
    out = Image.open(io.BytesIO(raw))
    assert out.format == "JPEG"
    assert max(out.size) <= 1024
    assert out.size == (1024, 512)   # アスペクト比維持


def test_encode_frame_no_upscale_small_image():
    src = Image.new("RGB", (640, 480), (0, 0, 0))
    out = Image.open(io.BytesIO(base64.b64decode(encode_frame(src, max_long_edge=1024))))
    assert out.size == (640, 480)


def test_encode_frame_converts_non_rgb():
    src = Image.new("RGBA", (100, 100), (1, 2, 3, 255))
    out = Image.open(io.BytesIO(base64.b64decode(encode_frame(src))))
    assert out.mode == "RGB"
```

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_capture.py -v`
Expected: FAIL（`ImportError: cannot import name 'encode_frame'`）

- [ ] **Step 4: 実装する**

`kotoha/screen/capture.py`:

```python
"""画面キャプチャ。縮小・エンコードは純関数、実キャプチャは遅延 import の薄い実装。

MssCapturer はクロスプラットフォーム(GDI)。DxcamCapturer は Windows の DXGI で
ゲーム画面も取得する。どちらも capture() は base64 JPEG か None を返す best-effort。
"""

import base64
import io
import logging

logger = logging.getLogger(__name__)


def encode_frame(image, *, max_long_edge: int = 1024, quality: int = 70) -> str:
    """PIL.Image を長辺 max_long_edge まで縮小し、JPEG base64(プレフィックス無し)にする。"""
    w, h = image.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))))
    if image.mode != "RGB":
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class MssCapturer:
    """mss(GDI) でプライマリモニタを取得する。"""

    def __init__(self, *, max_long_edge: int = 1024):
        self._max_long_edge = max_long_edge
        self._sct = None

    def _ensure(self):
        if self._sct is None:
            import mss   # 遅延 import
            self._sct = mss.mss()

    def capture(self) -> str | None:
        try:
            from PIL import Image   # 遅延 import
            self._ensure()
            mon = self._sct.monitors[1]   # [0]=全体, [1]=プライマリ
            raw = self._sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            return encode_frame(img, max_long_edge=self._max_long_edge)
        except Exception:
            logger.warning("mss capture failed", exc_info=True)
            return None


class DxcamCapturer:
    """dxcam(DXGI Desktop Duplication) でゲーム画面も取得する(Windows)。"""

    def __init__(self, *, max_long_edge: int = 1024):
        self._max_long_edge = max_long_edge
        self._cam = None

    def _ensure(self):
        if self._cam is None:
            import dxcam   # 遅延 import (dxcam-cpp も import 名は dxcam)
            self._cam = dxcam.create(output_color="RGB")

    def capture(self) -> str | None:
        try:
            from PIL import Image   # 遅延 import
            self._ensure()
            frame = self._cam.grab()   # 新フレームが無ければ None
            if frame is None:
                return None
            img = Image.fromarray(frame)   # H×W×3 RGB ndarray
            return encode_frame(img, max_long_edge=self._max_long_edge)
        except Exception:
            logger.warning("dxcam capture failed", exc_info=True)
            return None
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `pytest tests/screen/test_capture.py -v`
Expected: PASS（3 passed。Pillow 未導入環境では skipped）

- [ ] **Step 6: コミット**

```bash
git add pyproject.toml kotoha/screen/capture.py tests/screen/test_capture.py
git commit -m "feat(screen): add screen capture (mss/dxcam) and frame encoding

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: VLM クライアント（リクエスト生成・応答解析の純関数＋呼び出し）

**Files:**
- Create: `kotoha/llm/vlm_client.py`
- Test: `tests/llm/test_vlm_client.py`

**Interfaces:**
- Produces: `build_vlm_payload(image_b64, *, prompt, model, api) -> tuple[str, dict]`（`(path, payload)`）。`parse_vlm_response(obj, *, api) -> str`。`vlm_describe(image_b64, *, model, base_url, prompt, api="openai", session, timeout_s=20.0) -> str`。`api` は `"openai" | "ollama"`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/llm/test_vlm_client.py`:

```python
from kotoha.llm.vlm_client import build_vlm_payload, parse_vlm_response


def test_build_payload_openai():
    path, payload = build_vlm_payload("ZZZ", prompt="説明して", model="qwen3-vl:4b", api="openai")
    assert path == "/v1/chat/completions"
    assert payload["model"] == "qwen3-vl:4b"
    assert payload["stream"] is False
    content = payload["messages"][0]["content"]
    assert {"type": "text", "text": "説明して"} in content
    img = [c for c in content if c["type"] == "image_url"][0]
    assert img["image_url"]["url"] == "data:image/jpeg;base64,ZZZ"


def test_build_payload_ollama():
    path, payload = build_vlm_payload("ZZZ", prompt="説明して", model="qwen3-vl:4b", api="ollama")
    assert path == "/api/chat"
    msg = payload["messages"][0]
    assert msg["content"] == "説明して"
    assert msg["images"] == ["ZZZ"]
    assert payload["stream"] is False


def test_parse_response_openai():
    obj = {"choices": [{"message": {"content": "  画面にコード。 "}}]}
    assert parse_vlm_response(obj, api="openai") == "画面にコード。"


def test_parse_response_ollama():
    obj = {"message": {"content": "画面にブラウザ。"}}
    assert parse_vlm_response(obj, api="ollama") == "画面にブラウザ。"


def test_parse_response_empty():
    assert parse_vlm_response({"choices": []}, api="openai") == ""
    assert parse_vlm_response({}, api="ollama") == ""
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/llm/test_vlm_client.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装する**

`kotoha/llm/vlm_client.py`:

```python
"""画像つき推論クライアント。Ollama /api/chat と OpenAI 互換 /v1/chat/completions の両対応。

リクエスト生成と応答解析は純関数(front_client の parse_chat_line と同じ流儀)。
要約は短い日本語になるよう prompt 側で制約する。best-effort。
"""

import aiohttp


def build_vlm_payload(image_b64: str, *, prompt: str, model: str, api: str) -> tuple[str, dict]:
    """(path, payload) を返す。api は "openai" | "ollama"。"""
    if api == "ollama":
        return "/api/chat", {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        }
    data_uri = f"data:image/jpeg;base64,{image_b64}"
    return "/v1/chat/completions", {
        "model": model,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }],
    }


def parse_vlm_response(obj: dict, *, api: str) -> str:
    if api == "ollama":
        return (obj.get("message", {}).get("content") or "").strip()
    choices = obj.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


async def vlm_describe(
    image_b64: str,
    *,
    model: str,
    base_url: str,
    prompt: str,
    api: str = "openai",
    session: aiohttp.ClientSession,
    timeout_s: float = 20.0,
) -> str:
    """画像を VLM へ送り、短い要約文字列を返す。失敗は例外を投げる(呼び出し側で捕捉)。"""
    path, payload = build_vlm_payload(image_b64, prompt=prompt, model=model, api=api)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with session.post(f"{base_url}{path}", json=payload, timeout=timeout) as resp:
        resp.raise_for_status()
        obj = await resp.json()
    return parse_vlm_response(obj, api=api)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/llm/test_vlm_client.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/llm/vlm_client.py tests/llm/test_vlm_client.py
git commit -m "feat(llm): add VLM client for Ollama and OpenAI-compatible backends

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 知覚ループ（ScreenPerceiver）

**Files:**
- Create: `kotoha/screen/perceiver.py`
- Test: `tests/screen/test_perceiver.py`

**Interfaces:**
- Consumes: `ScreenContext`（Task 2）。`capturer.capture() -> str | None`（Task 4）。`describe(image_b64) -> str`（Task 5 の `vlm_describe` を partial で固めた async callable）。
- Produces: `ScreenPerceiver(*, capturer, describe, screen_ctx, normal_interval_s, realtime_interval_s, poll_s=2.0, sleep=asyncio.sleep)`。`async tick() -> bool`（1サイクル。要約更新で True）。`async run()`（停止まで tick とスリープ）。`stop()`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_perceiver.py`:

```python
import pytest

from kotoha.screen.state import ScreenContext
from kotoha.screen.perceiver import ScreenPerceiver


class _Capturer:
    def __init__(self, value="IMGB64"): self.value = value; self.calls = 0
    def capture(self):
        self.calls += 1
        return self.value


def _describe_factory(text):
    async def _describe(image_b64):
        return text
    return _describe


def _ctx():
    return ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)


async def test_tick_updates_summary():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_describe_factory("画面にエディタ。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is True
    assert ctx.get_summary() == "画面にエディタ。"


async def test_powersave_skips_capture():
    ctx = _ctx()
    ctx.set_mode("game_powersave")
    cap = _Capturer()
    p = ScreenPerceiver(
        capturer=cap, describe=_describe_factory("x"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is False
    assert cap.calls == 0
    assert ctx.get_summary() is None


async def test_capture_none_does_not_crash():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(value=None), describe=_describe_factory("x"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is False
    assert ctx.get_summary() is None


async def test_describe_exception_is_swallowed():
    ctx = _ctx()
    async def _boom(image_b64): raise RuntimeError("vlm down")
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_boom,
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5,
    )
    assert await p.tick() is False   # 会話を止めない


def test_interval_by_mode():
    ctx = _ctx()
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_describe_factory("x"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5, poll_s=2.0,
    )
    assert p._interval() == 4.0
    ctx.set_mode("game_realtime"); assert p._interval() == 0.5
    ctx.set_mode("game_powersave"); assert p._interval() == 2.0
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_perceiver.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装する**

`kotoha/screen/perceiver.py`:

```python
"""背景の画面知覚ループ。一定間隔でキャプチャし、VLM で要約して ScreenContext へ書く。

best-effort。capture / describe のどの失敗でも要約を更新しないだけで、例外を上へ投げない。
省力型ゲームモード中はキャプチャを行わない。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class ScreenPerceiver:
    def __init__(
        self,
        *,
        capturer,
        describe,
        screen_ctx,
        normal_interval_s: float,
        realtime_interval_s: float,
        poll_s: float = 2.0,
        sleep=asyncio.sleep,
    ):
        self._capturer = capturer
        self._describe = describe          # async (image_b64) -> str
        self._screen_ctx = screen_ctx
        self._normal_interval = normal_interval_s
        self._realtime_interval = realtime_interval_s
        self._poll_s = poll_s
        self._sleep = sleep
        self._stop = False

    def _interval(self) -> float:
        mode = self._screen_ctx.mode
        if mode == "game_realtime":
            return self._realtime_interval
        if mode == "game_powersave":
            return self._poll_s
        return self._normal_interval

    async def tick(self) -> bool:
        """1サイクル。要約を更新できたら True。"""
        if self._screen_ctx.mode == "game_powersave":
            return False
        try:
            image_b64 = self._capturer.capture()
        except Exception:
            logger.warning("screen capture raised", exc_info=True)
            return False
        if not image_b64:
            return False
        try:
            summary = await self._describe(image_b64)
        except Exception:
            logger.warning("VLM describe failed", exc_info=True)
            return False
        if summary:
            self._screen_ctx.set_summary(summary)
            return True
        return False

    async def run(self) -> None:
        while not self._stop:
            await self.tick()
            await self._sleep(self._interval())

    def stop(self) -> None:
        self._stop = True
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_perceiver.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/perceiver.py tests/screen/test_perceiver.py
git commit -m "feat(screen): add background ScreenPerceiver loop

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: ゲームモード監視（前面窓取得＋モード反映ループ）

**Files:**
- Modify: `kotoha/screen/detector.py`（前面窓取得とモード監視ループを追記）
- Test: `tests/screen/test_game_mode_loop.py`

**Interfaces:**
- Consumes: `is_game_active`, `resolve_mode`（Task 3）。`ScreenContext`（Task 2）。
- Produces: `get_foreground_info() -> dict | None`（OS 依存、best-effort）。`GameModeLoop(*, screen_ctx, config, get_foreground=get_foreground_info, sleep=asyncio.sleep)` with `async tick()`, `async run()`, `stop()`。`tick()` は前面窓を見てモードを `screen_ctx` に反映する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_game_mode_loop.py`:

```python
from kotoha.config import Config
from kotoha.screen.state import ScreenContext
from kotoha.screen.detector import GameModeLoop


def _loop(foreground, **overrides):
    ctx = ScreenContext(clock=lambda: 0.0)
    cfg = Config(**overrides)
    loop = GameModeLoop(screen_ctx=ctx, config=cfg, get_foreground=lambda: foreground)
    return ctx, loop


async def test_normal_when_no_game():
    ctx, loop = _loop({"fullscreen": False, "process": "notepad.exe"})
    await loop.tick()
    assert ctx.mode == "normal"


async def test_powersave_on_fullscreen_default():
    ctx, loop = _loop({"fullscreen": True, "process": "game.exe"})
    await loop.tick()
    assert ctx.mode == "game_powersave"


async def test_realtime_when_configured():
    ctx, loop = _loop({"fullscreen": True, "process": "game.exe"}, screen_game_mode="realtime")
    await loop.tick()
    assert ctx.mode == "game_realtime"


async def test_process_list_triggers_without_fullscreen():
    ctx, loop = _loop(
        {"fullscreen": False, "process": "EldenRing.exe"},
        screen_game_detect_fullscreen=False,
        screen_game_process_names=("eldenring",),
    )
    await loop.tick()
    assert ctx.mode == "game_powersave"
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_game_mode_loop.py -v`
Expected: FAIL（`ImportError: cannot import name 'GameModeLoop'`）

- [ ] **Step 3: 実装する**

`kotoha/screen/detector.py` の末尾に追記。

```python
import asyncio


def get_foreground_info():
    """前面窓の {"fullscreen": bool, "process": str} を返す(Windows)。失敗・非対応は None。

    ctypes で前面窓の矩形をプライマリ解像度と比べ、プロセス名を取得する best-effort。
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        sw = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        sh = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        fullscreen = (rect.left <= 0 and rect.top <= 0
                      and rect.right >= sw and rect.bottom >= sh)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = buf.value
            finally:
                kernel32.CloseHandle(h)
        return {"fullscreen": bool(fullscreen), "process": name}
    except Exception:
        logger.warning("get_foreground_info failed", exc_info=True)
        return None


class GameModeLoop:
    """前面窓を定期監視し、ゲーム判定の結果を ScreenContext のモードへ反映する。"""

    def __init__(self, *, screen_ctx, config, get_foreground=get_foreground_info,
                 sleep=asyncio.sleep):
        self._ctx = screen_ctx
        self._config = config
        self._get_foreground = get_foreground
        self._sleep = sleep
        self._stop = False

    async def tick(self) -> None:
        try:
            fg = self._get_foreground()
        except Exception:
            logger.warning("foreground probe failed", exc_info=True)
            return
        active = is_game_active(
            fg,
            detect_fullscreen=self._config.screen_game_detect_fullscreen,
            process_names=self._config.screen_game_process_names,
        )
        self._ctx.set_mode(resolve_mode(active, self._config.screen_game_mode))

    async def run(self) -> None:
        while not self._stop:
            await self.tick()
            await self._sleep(self._config.screen_game_poll_s)

    def stop(self) -> None:
        self._stop = True
```

ファイル先頭の `import asyncio` が重複する場合は先頭の import 群へまとめる。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_game_mode_loop.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/detector.py tests/screen/test_game_mode_loop.py
git commit -m "feat(screen): add foreground probe and game-mode monitor loop

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: persona に画面ガイドを追加

**Files:**
- Modify: `kotoha/llm/persona.py`（`STYLE_PROMPT` に1文追記）
- Test: `tests/llm/test_persona.py`

**Interfaces:**
- Produces: `SYSTEM_PROMPT`/`IMMUTABLE_PROMPT` に画面言及のガイドを含む。

- [ ] **Step 1: 失敗するテストを書く**

`tests/llm/test_persona.py` に追記。

```python
def test_style_prompt_has_screen_guidance():
    from kotoha.llm import persona
    assert "画面の様子" in persona.SYSTEM_PROMPT
    assert "毎回" in persona.SYSTEM_PROMPT   # 「毎回実況しない」
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/llm/test_persona.py::test_style_prompt_has_screen_guidance -v`
Expected: FAIL（`AssertionError`）

- [ ] **Step 3: 実装する**

`kotoha/llm/persona.py` の `STYLE_PROMPT` の最後の文字列要素（`"語尾は..."` の行）の直後に1行追記する。

```python
    "「画面の様子」が示されたら、聞かれたときや明らかに関係するときだけ自然に触れる。毎回画面の内容を実況しない。"
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/llm/test_persona.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/llm/persona.py tests/llm/test_persona.py
git commit -m "feat(persona): guide tsukuyomi to mention screen only when relevant

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Orchestrator への画面要約注入

**Files:**
- Modify: `kotoha/orchestrator.py`（`__init__` に `screen_context=None` を追加、`handle_utterance` に注入ブロックを追加）
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `ScreenContext.get_summary() -> str | None`（Task 2）。
- Produces: `Orchestrator(..., screen_context=None)`。`handle_utterance` が時刻・地点 system メッセージの後に画面要約 system メッセージを注入する（要約がある場合のみ）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_orchestrator.py` に追記。自己完結の fake を使う。

```python
import numpy as np
import pytest

from kotoha.orchestrator import Orchestrator


class _FakeTranscriber:
    def __init__(self, text): self._t = text
    def transcribe(self, audio): return self._t


class _CaptureStream:
    """llm_stream 互換。渡された messages を記録し、空ストリームを返す。"""
    def __init__(self): self.messages = None
    def __call__(self, messages, *, model):
        self.messages = messages
        async def _gen():
            return
            yield ""   # 到達しない(空の async generator)
        return _gen()


class _FakeScreen:
    def __init__(self, summary): self._s = summary
    def get_summary(self): return self._s


async def _noop_tts(text): return b""


def _build(stream, screen):
    return Orchestrator(
        transcriber=_FakeTranscriber("いまどう?"),
        llm_stream=stream,
        tts=_noop_tts,
        player=object(),
        model="m",
        vad_factory=lambda: object(),
        screen_context=screen,
    )


async def test_screen_summary_injected_when_present():
    stream = _CaptureStream()
    orch = _build(stream, _FakeScreen("画面にコードエディタが映っている。"))
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    contents = [m["content"] for m in stream.messages if m["role"] == "system"]
    assert any(c.startswith("【画面の様子】") for c in contents)
    assert any("画面にコードエディタ" in c for c in contents)


async def test_no_screen_message_when_summary_none():
    stream = _CaptureStream()
    orch = _build(stream, _FakeScreen(None))
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    contents = [m["content"] for m in stream.messages if m["role"] == "system"]
    assert not any(c.startswith("【画面の様子】") for c in contents)


async def test_no_screen_context_is_fine():
    stream = _CaptureStream()
    orch = _build(stream, None)
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    assert stream.messages is not None   # 落ちずに通る
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_orchestrator.py -k screen -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'screen_context'`）

- [ ] **Step 3: 実装する**

`kotoha/orchestrator.py` の `__init__` 署名に追加（`place: str = "",` の後）。

```python
        place: str = "",
        screen_context=None,
```

`__init__` 本体の `self._place = place` の後に追加。

```python
        self._screen_context = screen_context   # 最新の画面要約を毎ターン注入(任意)
```

`handle_utterance` の「現在の状況」注入（`format_turn_context` の `messages.insert(-1, ...)` ブロック）の直後に追加。

```python
        # 画面知覚: 最新の画面要約があれば、状況の後に注入する(best-effort・任意)。
        if self._screen_context is not None:
            summary = self._screen_context.get_summary()
            if summary:
                messages.insert(-1, {
                    "role": "system",
                    "content": (
                        "【画面の様子】\n" + summary
                        + "\n画面の話は、聞かれたときや明らかに関係するときだけ自然に触れる。"
                    ),
                })
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS（既存テスト含め緑。回帰なし）

- [ ] **Step 5: コミット**

```bash
git add kotoha/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): inject latest screen summary into turn context

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 記憶・関係性の補助エンドポイント振り分けと省力ゲート

**Files:**
- Modify: `kotoha/memory/manager.py`（`background_gate` 追加、`_run_compress` の base_url を aux へ）
- Modify: `kotoha/relationship/manager.py`（`background_gate` 追加、`_run_analyze` の base_url を aux へ）
- Test: `tests/memory/test_manager.py`, `tests/relationship/test_manager.py`

**Interfaces:**
- Consumes: `Config.aux_llm_url`（Task 1）、`ScreenContext.background_llm_allowed`（Task 2、`local_app` から callable として注入）。
- Produces: `MemoryManager(..., background_gate=None)` と `RelationshipManager(..., background_gate=None)`。`background_gate` が `False` を返す間は背景 LLM ジョブを起動しない。両者の背景 LLM 呼び出し base_url は `config.aux_llm_url or config.ollama_url`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/relationship/test_manager.py` に追記。

```python
from kotoha.config import Config
from kotoha.relationship.manager import RelationshipManager


class _Store:
    def __init__(self): self.affection = 50; self.last_day = ""
    def save(self): pass


def _mgr(gate, spawned):
    return RelationshipManager(
        store=_Store(), config=Config(), session=object(), loop=object(),
        analyze_fn=lambda *a, **k: None,
        spawn=lambda coro: spawned.append(coro),
        clock=__import__("datetime").datetime.now,
        background_gate=gate,
    )


def test_gate_blocks_background_analyze():
    spawned = []
    _mgr(lambda: False, spawned).on_turn("hi")
    assert spawned == []


def test_gate_allows_background_analyze():
    spawned = []
    _mgr(lambda: True, spawned).on_turn("hi")
    assert len(spawned) == 1
    for c in spawned:   # 未 await のコルーチンを閉じて警告を防ぐ
        c.close()


def test_no_gate_allows_by_default():
    spawned = []
    _mgr(None, spawned).on_turn("hi")
    assert len(spawned) == 1
    for c in spawned:
        c.close()
```

`tests/memory/test_manager.py` に追記。

```python
from kotoha.config import Config
from kotoha.memory.manager import MemoryManager


class _Store:
    def __init__(self):
        self.raw_window = []
        self.pending_raw = [{"role": "user", "content": "x"}]
        self.turns_since_compress = 0
        self.short_term = []
    def save(self): pass


def _mgr(gate, spawned, **cfg):
    config = Config(memory_compress_interval=1, memory_keep_recent_turns=10, **cfg)
    return MemoryManager(
        store=_Store(), config=config, session=object(), loop=object(),
        compress_fn=lambda *a, **k: [], spawn=lambda coro: spawned.append(coro),
        background_gate=gate,
    )


def test_gate_blocks_compress():
    spawned = []
    _mgr(lambda: False, spawned).on_turn_end("hello")
    assert spawned == []


def test_gate_allows_compress():
    spawned = []
    _mgr(lambda: True, spawned).on_turn_end("hello")
    assert len(spawned) == 1
    for c in spawned:
        c.close()
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/relationship/test_manager.py tests/memory/test_manager.py -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'background_gate'`）

- [ ] **Step 3: 実装する**

`kotoha/relationship/manager.py`。`__init__` 署名に `background_gate=None` を追加し（`clock=None` の後）、本体に `self._background_gate = background_gate` を追加。`on_turn` を次に変える。

```python
    def on_turn(self, user_text: str, context=None) -> None:
        self._maybe_new_day()
        # 背景分析(4b)はVRAM/速度に響くため、無効時は値を固定したまま注入のみにする。
        if not getattr(self.config, "relationship_analyze_enabled", True):
            return
        # 省力型ゲームモード中などは背景LLMを起動しない。
        if self._background_gate is not None and not self._background_gate():
            return
        self._spawn(self._run_analyze(user_text, context))
```

`_run_analyze` の `base_url=self.config.ollama_url,` を次に変える。

```python
                    base_url=self.config.aux_llm_url or self.config.ollama_url,
```

`kotoha/memory/manager.py`。`__init__` 署名に `background_gate=None` を追加し（`clock=None,` の後）、本体に `self._background_gate = background_gate` を追加。`on_turn_end` 末尾の起動条件を次に変える。

```python
        if self.store.turns_since_compress >= self.N and self.store.pending_raw:
            if self._background_gate is None or self._background_gate():
                self._spawn(self._run_compress())
```

`_run_compress` の `base_url=self.config.ollama_url,` を次に変える。

```python
                base_url=self.config.aux_llm_url or self.config.ollama_url,
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/relationship/test_manager.py tests/memory/test_manager.py -v`
Expected: PASS（既存テスト含め緑）

- [ ] **Step 5: コミット**

```bash
git add kotoha/memory/manager.py kotoha/relationship/manager.py tests/memory/test_manager.py tests/relationship/test_manager.py
git commit -m "feat(memory,relationship): route bg LLM to aux endpoint with pause gate

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 配線（local_app）と環境変数・extra

**Files:**
- Modify: `kotoha/local_app.py`（`build_orchestrator` に `screen_context` 追加、`run_local` で知覚を起動・配線）
- Modify: `.env.example`（接続先上書きキーを追記）
- Test: `tests/test_local_app.py`

**Interfaces:**
- Consumes: Task 1〜10 の全成果。
- Produces: `build_orchestrator(..., screen_context=None)` が `screen_context` を `Orchestrator` へ渡す。`run_local` が `screen_perception_enabled` のとき `ScreenContext`・Capturer・`ScreenPerceiver`・`GameModeLoop` を起動し、`screen_context` と `background_gate` を orchestrator/記憶/関係性へ配る。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_local_app.py` に追記。

```python
def test_build_orchestrator_passes_screen_context():
    from kotoha.config import Config
    from kotoha.local_app import build_orchestrator

    sentinel = object()
    orch = build_orchestrator(
        Config(),
        session=object(),
        loop=None,
        transcriber=object(),
        player=object(),
        screen_context=sentinel,
    )
    assert orch._screen_context is sentinel
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_local_app.py::test_build_orchestrator_passes_screen_context -v`
Expected: FAIL（`TypeError: build_orchestrator() got an unexpected keyword argument 'screen_context'`）

- [ ] **Step 3: build_orchestrator を実装する**

`kotoha/local_app.py` の `build_orchestrator` 署名に `screen_context=None` を追加（`relationship=None,` の後）。

```python
    relationship=None,
    screen_context=None,
):
```

`return Orchestrator(...)` の最後の引数 `place=_display_place(config),` の後に追加。

```python
        place=_display_place(config),
        screen_context=screen_context,
    )
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/test_local_app.py::test_build_orchestrator_passes_screen_context -v`
Expected: PASS

- [ ] **Step 5: run_local に知覚の起動・配線を追加する**

`kotoha/local_app.py` の import 群に追加。

```python
import functools  # 既存
from kotoha.screen.state import ScreenContext
from kotoha.screen.capture import MssCapturer, DxcamCapturer
from kotoha.screen.perceiver import ScreenPerceiver
from kotoha.screen.detector import GameModeLoop
from kotoha.llm.vlm_client import vlm_describe
```

`run_local` の `relationship` 構築ブロックの後、`remote_server` ブロックの前に、`screen_ctx` と背景タスクを用意する。

```python
        # 画面知覚(任意・既定OFF)。VLM は base_url で別バックエンド(VII 等)を指せる。
        screen_ctx = None
        screen_tasks = []
        if config.screen_perception_enabled:
            screen_ctx = ScreenContext(summary_max_age_s=config.screen_summary_max_age_s)
            if config.screen_capture_backend == "dxcam":
                capturer = DxcamCapturer(max_long_edge=config.screen_capture_max_long_edge)
            else:
                capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)
            describe = functools.partial(
                vlm_describe,
                model=config.vlm_perception_model,
                base_url=config.vlm_perception_url or config.ollama_url,
                prompt=config.vlm_perception_prompt,
                api=config.vlm_perception_api,
                session=session,
                timeout_s=config.vlm_perception_timeout_s,
            )
            perceiver = ScreenPerceiver(
                capturer=capturer, describe=describe, screen_ctx=screen_ctx,
                normal_interval_s=config.screen_normal_interval_s,
                realtime_interval_s=config.screen_game_realtime_interval_s,
                poll_s=config.screen_game_poll_s,
            )
            game_loop = GameModeLoop(screen_ctx=screen_ctx, config=config)
            screen_tasks = [
                loop.create_task(perceiver.run()),
                loop.create_task(game_loop.run()),
            ]
            print("[screen] perception enabled "
                  f"(backend={config.screen_capture_backend}, vlm={config.vlm_perception_model})")
```

`background_gate` を記憶・関係性へ配るため、`memory` 構築の `MemoryManager(...)` 呼び出しに引数を足す。

```python
            memory = MemoryManager(
                store=store,
                config=config,
                session=session,
                loop=loop,
                gemini_models=model_chain,
                api_key=api_key,
                background_gate=(screen_ctx.background_llm_allowed if screen_ctx else None),
            )
```

同様に `relationship` 構築の `RelationshipManager(...)` に足す。

```python
            relationship = RelationshipManager(
                store=rstore, config=config, session=session, loop=loop,
                background_gate=(screen_ctx.background_llm_allowed if screen_ctx else None),
            )
```

注意。`screen_ctx` は `memory`/`relationship` 構築より前に作る必要がある。上の「画面知覚」ブロックを、`memory = None` ブロックより前へ置く（health チェックの後、`bridge` ブロックの後あたり）。

`build_orchestrator(...)` 呼び出しに `screen_context=screen_ctx` を追加する。

```python
        orch = build_orchestrator(
            config,
            session=session,
            loop=loop,
            events=events,
            on_amplitude=on_amplitude,
            memory=memory,
            relationship=relationship,
            player=player,
            screen_context=screen_ctx,
        )
```

シャットダウンの `finally:` ブロックに停止処理を足す（`if bridge is not None:` の前）。

```python
            for t in screen_tasks:
                t.cancel()
```

- [ ] **Step 6: .env.example を更新する**

`.env.example` の末尾に追記。

```bash
# 画面知覚(任意)。非リアルタイム推論を別GPU(例 Radeon VII の Vulkan サーバ)へ向ける。
# 空ならローカルの Ollama(OLLAMA_URL 既定) を使う。
VLM_PERCEPTION_URL=
AUX_LLM_URL=
```

（注。env からの上書きが必要なら、`local_app.py` で `os.environ.get("VLM_PERCEPTION_URL")` 等を読んで `Config` 構築時に渡す配線を足す。Phase 1 既定はコード内 `Config` の値で動くため、env 連携は任意。）

- [ ] **Step 7: テスト全体を実行**

Run: `pytest -m "not integration" -q`
Expected: 既存＋新規がすべて PASS（回帰なし）

- [ ] **Step 8: コミット**

```bash
git add kotoha/local_app.py .env.example tests/test_local_app.py
git commit -m "feat(screen): wire screen perception into local app lifecycle

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 実機確認（integration・proof 環境）

ユニットでは担保しない実機部分。proof 環境（4080 + Radeon VII）で目視確認する。

- VII で llama.cpp の Vulkan サーバ（OpenAI 互換）を `qwen3-vl:4b` ＋ mmproj で起動し、`GGML_VK_VISIBLE_DEVICES` で VII を指定、4080 の Ollama と別ポートにする。`vlm_perception_url`/`aux_llm_url` を VII へ向ける。
- `screen_perception_enabled=True` でつくよみが画面内容に触れること、通常時は数秒間隔で会話を妨げないこと。
- ゲーム起動でモードが切り替わること。省力型で記憶・関係性・知覚が止まること、リアルタイム型で dxcam が高頻度に取得すること。
- VLM/キャプチャを落としても会話が継続すること。

## Self-Review（記入済み）

- **Spec coverage:** 方針→Task 9/11、採用部品→Task 4/5/11、`kotoha/screen/` の各コンポーネント→Task 2/3/4/6/7、ルーティング→Task 1/5/10/11、動作モード→Task 6/7/10、設定→Task 1、プライバシー→Global Constraints＋Task 4（ディスク非保存）、エラー処理→Task 4/5/6、テスト→各タスク、受け入れ基準→実機確認節。網羅を確認。
- **Placeholder scan:** プレースホルダなし。各コード手順に実コードを記載。
- **Type consistency:** `capture() -> str|None`、`describe(image_b64)` async、`get_summary() -> str|None`、`background_llm_allowed() -> bool`、`resolve_mode`/`is_game_active` の引数名はタスク間で一致。`screen_context`/`background_gate` の名前も一貫。
