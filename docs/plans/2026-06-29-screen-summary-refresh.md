# 画面要約の品質刷新 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 知覚ループの重複再要約を perceptual-hash 変化検出で減らし、画面要約に前面アプリ名を添える。

**Architecture:** 純ロジックの `phash.py` を新設し、`ScreenPerceiver` の完全一致 dedup を hamming 距離判定へ置換。`ScreenContext` に app を持たせ、perceiver が前面アプリ名を注入で取得して要約と一緒に保存、orchestrator がアプリ付きで会話へ注入する。設計の正は [docs/specs/2026-06-29-screen-summary-refresh-design.md](../specs/2026-06-29-screen-summary-refresh-design.md)。

**Tech Stack:** Python 3.11+, numpy, PIL(いずれも既存)。新規依存なし。

## Global Constraints

- Python は `>=3.11`。ユニット検証は手元の 3.10 で行う。
- 新規依存を増やさない。`phash` は PIL と numpy のみ。
- best-effort を崩さない。`dhash_b64` のデコード失敗・`get_foreground` の例外で会話ループを止めない。
- 画面知覚は既定 OFF のオプトイン。本変更は有効時の挙動改善で、無効時は何も変えない。後方互換: `set_summary(text, app="")`、`ScreenPerceiver(..., change_threshold=0, get_foreground=None)` の既定で既存呼び出しと挙動一致。
- ユニットは GPU・実画面・外部サービスなしで通す(fake 注入)。既定実行 `pytest -m "not integration"`。
- コミットは Conventional Commits。タイトル英語。本文末尾に空行＋`Co-Authored-By: Claude <noreply@anthropic.com>`。author は `4ltena`。

## ファイル構成

- 新規 `kotoha/screen/phash.py` — `dhash` / `hamming` / `dhash_b64`(純)。
- 修正 `kotoha/config.py` — `screen_change_hash_threshold: int = 4`。
- 修正 `kotoha/screen/perceiver.py` — 知覚ハッシュ変化検出、`get_foreground` 注入、app 引き渡し。
- 修正 `kotoha/screen/state.py` — `set_summary(text, app="")` と `get_app()`。
- 修正 `kotoha/orchestrator.py` — アプリ付き要約注入。
- 修正 `kotoha/local_app.py` — perceiver へ `change_threshold` と `get_foreground` を渡す。
- 新規 `tests/screen/test_phash.py`、各既存テストへ追記。

---

### Task 1: phash.py と config 閾値

**Files:**
- Create: `kotoha/screen/phash.py`
- Modify: `kotoha/config.py`
- Test: `tests/screen/test_phash.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `dhash(image, hash_size=8) -> int`、`hamming(a, b) -> int`、`dhash_b64(image_b64) -> int`、`Config.screen_change_hash_threshold: int = 4`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_phash.py`:

```python
import base64
import io

from PIL import Image

from kotoha.screen.phash import dhash, dhash_b64, hamming


def _img(color):
    return Image.new("RGB", (64, 64), color)


def _b64(image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_identical_images_have_zero_distance():
    a = dhash(_img((120, 120, 120)))
    b = dhash(_img((120, 120, 120)))
    assert hamming(a, b) == 0


def test_very_different_images_have_large_distance():
    # 左右半分で白黒に分けた画像 vs 一様灰色。dhash は構造差を拾う。
    split = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(32, 64):
        for y in range(64):
            split.putpixel((x, y), (255, 255, 255))
    assert hamming(dhash(split), dhash(_img((120, 120, 120)))) >= 8


def test_dhash_b64_matches_dhash_of_decoded():
    img = _img((30, 200, 90))
    assert hamming(dhash_b64(_b64(img)), dhash(img)) <= 2   # JPEG 量子化の許容


def test_hash_is_64_bit_for_default_size():
    assert 0 <= dhash(_img((10, 20, 30))) < (1 << 64)
```

`tests/test_config.py` に追記:

```python
def test_screen_change_hash_threshold_default():
    from kotoha.config import Config
    assert Config().screen_change_hash_threshold == 4
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_phash.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.screen.phash`）

- [ ] **Step 3: 実装する**

`kotoha/screen/phash.py`:

```python
"""difference hash(dhash)による画面の知覚的変化検出。純ロジック、PIL と numpy のみ。

完全一致では拾ってしまうカーソル点滅や時計更新のような微小変化を吸収し、
意味のある変化のときだけ再要約させるために使う。
"""

import base64
import io

import numpy as np


def dhash(image, hash_size: int = 8) -> int:
    """PIL.Image を difference hash(hash_size*hash_size ビット)の整数にする。"""
    img = image.convert("L").resize((hash_size + 1, hash_size))
    px = np.asarray(img, dtype=np.int16)
    diff = px[:, 1:] > px[:, :-1]   # 横方向の隣接画素の大小
    bits = 0
    for b in diff.flatten():
        bits = (bits << 1) | int(b)
    return bits


def hamming(a: int, b: int) -> int:
    """2つのハッシュのビット差。"""
    return bin(a ^ b).count("1")


def dhash_b64(image_b64: str, hash_size: int = 8) -> int:
    """base64 JPEG をデコードして dhash を返す。"""
    from PIL import Image   # 遅延 import
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw))
    return dhash(img, hash_size=hash_size)
```

`kotoha/config.py` の `aux_llm_url` フィールド付近(画面知覚ブロックの末尾)に追記:

```python
    screen_change_hash_threshold: int = 4          # 知覚ハッシュの hamming 距離。これ以下は微小変化として再要約しない
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_phash.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/phash.py kotoha/config.py tests/screen/test_phash.py tests/test_config.py
git commit -m "feat(screen): add perceptual dhash for change detection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: ScreenPerceiver の知覚ハッシュ変化検出

**Files:**
- Modify: `kotoha/screen/perceiver.py`
- Test: `tests/screen/test_perceiver.py`

**Interfaces:**
- Consumes: `dhash_b64`、`hamming`(Task 1)。
- Produces: `ScreenPerceiver(..., change_threshold=0)`。`tick` が完全一致でなく hamming 距離 `<= change_threshold` で skip する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_perceiver.py` に追記。下の fake capturer は「呼ぶたびに少しだけ違う / 大きく違う」base64 を返す。

```python
import base64
import io

from PIL import Image


def _frame_b64(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _SeqCapturer:
    def __init__(self, colors):
        self._frames = [_frame_b64(c) for c in colors]
        self._i = 0

    def capture(self):
        f = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return f


async def test_skips_describe_on_perceptually_similar_frame():
    ctx = _ctx()
    calls = []

    async def describe(image_b64):
        calls.append(image_b64)
        return "画面。"

    p = ScreenPerceiver(
        capturer=_SeqCapturer([(120, 120, 120), (121, 121, 121)]),
        describe=describe, screen_ctx=ctx,
        normal_interval_s=4.0, realtime_interval_s=0.5, change_threshold=4,
    )
    await p.tick()   # 1枚目: describe
    await p.tick()   # 2枚目: ほぼ同一 -> skip
    assert len(calls) == 1


async def test_describes_on_large_change():
    ctx = _ctx()
    calls = []

    async def describe(image_b64):
        calls.append(image_b64)
        return "画面。"

    split = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(32, 64):
        for y in range(64):
            split.putpixel((x, y), (255, 255, 255))
    buf = io.BytesIO()
    split.save(buf, format="JPEG", quality=70)
    split_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    class _TwoFrames:
        def __init__(self): self._i = 0
        def capture(self):
            self._i += 1
            return _frame_b64((120, 120, 120)) if self._i == 1 else split_b64

    p = ScreenPerceiver(
        capturer=_TwoFrames(), describe=describe, screen_ctx=ctx,
        normal_interval_s=4.0, realtime_interval_s=0.5, change_threshold=4,
    )
    await p.tick()
    await p.tick()
    assert len(calls) == 2
```

注。`_ctx()` は既存テストのヘルパ。無ければ `ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)`。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_perceiver.py -k "perceptually or large_change" -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'change_threshold'`）

- [ ] **Step 3: 実装する**

`kotoha/screen/perceiver.py` の import に追記:

```python
from kotoha.screen.phash import dhash_b64, hamming
```

`__init__` 署名へ `stats=None,` の後に追加:

```python
        change_threshold: int = 0,
        get_foreground=None,
```

`__init__` 本体の `self._last_capture_b64 = None` を置換:

```python
        self._last_hash = None
        self._change_threshold = change_threshold
        self._get_foreground = get_foreground
```

`tick` の完全一致ブロック(`if image_b64 == self._last_capture_b64:` 〜 `return False`)を置換:

```python
        try:
            h = dhash_b64(image_b64)
        except Exception:
            logger.warning("dhash failed; skipping frame", exc_info=True)
            if self._stats is not None:
                self._stats.record_skip()
            return False
        if self._last_hash is not None and hamming(h, self._last_hash) <= self._change_threshold:
            # 画面が実質変わっていない: 重い VLM を呼ばず、要約の鮮度だけ更新する。
            self._screen_ctx.touch()
            if self._stats is not None:
                self._stats.record_skip()
            return False
```

`tick` の要約更新ブロック(`if summary:` 内)の `self._last_capture_b64 = image_b64` を置換:

```python
            self._last_hash = h
```

（app の引き渡しは Task 4 で追加する。本タスクでは `set_summary(summary)` のまま。）

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_perceiver.py -v`
Expected: PASS（既存の perceiver テスト含め緑）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/perceiver.py tests/screen/test_perceiver.py
git commit -m "feat(screen): use perceptual hash distance for change detection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: ScreenContext のアプリ保持

**Files:**
- Modify: `kotoha/screen/state.py`
- Test: `tests/screen/test_state.py`

**Interfaces:**
- Produces: `set_summary(text, app="")`、`get_app() -> str`（有効要約があるときだけ app、無ければ ""）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_state.py` に追記:

```python
def test_set_summary_keeps_app():
    from kotoha.screen.state import ScreenContext
    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    ctx.set_summary("メモを書いている。", app="notepad.exe")
    assert ctx.get_summary() == "メモを書いている。"
    assert ctx.get_app() == "notepad.exe"


def test_get_app_empty_when_summary_expired():
    from kotoha.screen.state import ScreenContext
    t = {"now": 0.0}
    ctx = ScreenContext(summary_max_age_s=10.0, clock=lambda: t["now"])
    ctx.set_summary("x", app="chrome.exe")
    t["now"] = 100.0   # 期限切れ
    assert ctx.get_summary() is None
    assert ctx.get_app() == ""


def test_get_app_empty_by_default():
    from kotoha.screen.state import ScreenContext
    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    ctx.set_summary("x")
    assert ctx.get_app() == ""
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_state.py -k app -v`
Expected: FAIL（`TypeError: set_summary() got an unexpected keyword argument 'app'`）

- [ ] **Step 3: 実装する**

`kotoha/screen/state.py` の `__init__` に `self._app = ""` を追記(`self._summary = ""` の後)。

`set_summary` を置換:

```python
    def set_summary(self, text: str, app: str = "") -> None:
        with self._lock:
            self._summary = (text or "").strip()
            self._app = (app or "").strip()
            self._ts = self._clock()
```

`get_summary` の後に追記:

```python
    def get_app(self) -> str:
        """有効な最新要約があるときの前面アプリ名。無効・期限切れ・未設定は ""。"""
        with self._lock:
            if not self._summary or self._ts is None:
                return ""
            if (self._clock() - self._ts) > self._max_age:
                return ""
            return self._app
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_state.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/state.py tests/screen/test_state.py
git commit -m "feat(screen): hold foreground app alongside summary in ScreenContext

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: perceiver が前面アプリを要約へ渡す + local_app 配線

**Files:**
- Modify: `kotoha/screen/perceiver.py`
- Modify: `kotoha/local_app.py`
- Test: `tests/screen/test_perceiver.py`

**Interfaces:**
- Consumes: `ScreenContext.set_summary(text, app)`（Task 3）、`ScreenPerceiver.get_foreground`（Task 2 で署名追加済み）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_perceiver.py` に追記:

```python
async def test_passes_foreground_app_to_set_summary():
    recorded = {}

    class _Ctx:
        mode = "normal"
        def set_summary(self, text, app=""): recorded["app"] = app
        def touch(self): pass

    async def describe(image_b64): return "画面。"

    p = ScreenPerceiver(
        capturer=_SeqCapturer([(10, 20, 30)]), describe=describe, screen_ctx=_Ctx(),
        normal_interval_s=4.0, realtime_interval_s=0.5,
        get_foreground=lambda: "code.exe",
    )
    await p.tick()
    assert recorded["app"] == "code.exe"


async def test_foreground_exception_falls_back_to_empty_app():
    recorded = {}

    class _Ctx:
        mode = "normal"
        def set_summary(self, text, app=""): recorded["app"] = app
        def touch(self): pass

    async def describe(image_b64): return "画面。"

    def boom(): raise RuntimeError("no fg")

    p = ScreenPerceiver(
        capturer=_SeqCapturer([(10, 20, 30)]), describe=describe, screen_ctx=_Ctx(),
        normal_interval_s=4.0, realtime_interval_s=0.5, get_foreground=boom,
    )
    await p.tick()
    assert recorded["app"] == ""
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_perceiver.py -k foreground -v`
Expected: FAIL（app が渡らず KeyError、または None）

- [ ] **Step 3: 実装する**

`kotoha/screen/perceiver.py` の要約更新ブロックの `self._screen_ctx.set_summary(summary)` を置換:

```python
            app = ""
            if self._get_foreground is not None:
                try:
                    app = self._get_foreground() or ""
                except Exception:
                    logger.warning("get_foreground failed", exc_info=True)
                    app = ""
            self._screen_ctx.set_summary(summary, app=app)
```

`kotoha/local_app.py` の `ScreenPerceiver(...)` 構築(知覚有効ブロック)に引数を追加。`get_foreground_info` を import 済みでなければ知覚ブロック内で `from kotoha.screen.detector import get_foreground_info` する。

```python
            perceiver = ScreenPerceiver(
                capturer=capturer, describe=describe, screen_ctx=screen_ctx,
                normal_interval_s=config.screen_normal_interval_s,
                realtime_interval_s=config.screen_game_realtime_interval_s,
                poll_s=config.screen_game_poll_s, stats=screen_stats,
                change_threshold=config.screen_change_hash_threshold,
                get_foreground=lambda: (get_foreground_info() or {}).get("process", ""),
            )
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_perceiver.py -v`
Expected: PASS

- [ ] **Step 5: 全体テスト**

Run: `pytest -m "not integration" -q`
Expected: 回帰なしで全 PASS

- [ ] **Step 6: コミット**

```bash
git add kotoha/screen/perceiver.py kotoha/local_app.py tests/screen/test_perceiver.py
git commit -m "feat(screen): capture foreground app into the screen summary

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: orchestrator のアプリ付き注入

**Files:**
- Modify: `kotoha/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `ScreenContext.get_app()`（Task 3）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_orchestrator.py` に追記:

```python
async def test_screen_summary_injected_with_app_prefix():
    import numpy as np
    from kotoha.llm import persona
    from kotoha.orchestrator import Orchestrator
    from kotoha.screen.state import ScreenContext

    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    ctx.set_summary("コードを書いている。", app="code.exe")

    captured = []

    def llm(messages, *, model):
        captured.append([dict(m) for m in messages])

        async def gen():
            yield "はい。"
        return gen()

    async def tts(text): return b""

    class _Tr:
        def transcribe(self, audio): return "いまどう?"

    class _Player:
        def is_playing(self): return False
        def stop(self): pass
        async def play_and_wait(self, wav): return True

    orch = Orchestrator(
        transcriber=_Tr(), llm_stream=llm, tts=tts, player=_Player(),
        model="m", vad_factory=lambda: object(), persona=persona, screen_context=ctx,
    )
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    sys_contents = [m["content"] for m in captured[0] if m["role"] == "system"]
    assert any("(アプリ: code.exe)" in c and "コードを書いている" in c for c in sys_contents)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_orchestrator.py -k app_prefix -v`
Expected: FAIL（注入に `(アプリ: ...)` が無い）

- [ ] **Step 3: 実装する**

`kotoha/orchestrator.py` の画面知覚注入ブロックを置換:

```python
        if self._screen_context is not None:
            summary = self._screen_context.get_summary()
            if summary:
                app = ""
                getter = getattr(self._screen_context, "get_app", None)
                if callable(getter):
                    app = getter() or ""
                head = f"(アプリ: {app})\n" if app else ""
                messages.insert(-1, {
                    "role": "system",
                    "content": (
                        "【画面の様子】" + ("\n" if not head else "\n" + head[:-1] + "\n")
                        + summary
                        + "\n画面の話は、聞かれたときや明らかに関係するときだけ自然に触れる。"
                    ),
                })
```

注。可読性のため次のより素直な形でよい(同義):

```python
        if self._screen_context is not None:
            summary = self._screen_context.get_summary()
            if summary:
                getter = getattr(self._screen_context, "get_app", None)
                app = (getter() or "") if callable(getter) else ""
                prefix = f"(アプリ: {app})\n" if app else ""
                messages.insert(-1, {
                    "role": "system",
                    "content": (
                        "【画面の様子】\n" + prefix + summary
                        + "\n画面の話は、聞かれたときや明らかに関係するときだけ自然に触れる。"
                    ),
                })
```

後者を採用する。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS（既存テストも緑。app 無しの既存ケースは従来どおり `【画面の様子】\n<summary>`）

- [ ] **Step 5: 全体テスト**

Run: `pytest -m "not integration" -q`
Expected: 全 PASS

- [ ] **Step 6: コミット**

```bash
git add kotoha/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): prefix screen summary with the foreground app

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review（記入済み）

- **Spec coverage:** Part A(知覚ハッシュ)→Task 1+2、Part B(アプリ文脈)→Task 3+4+5。設定→Task 1。網羅を確認。
- **Placeholder scan:** なし。各手順に実コード。
- **Type consistency:** `dhash/hamming/dhash_b64`、`ScreenPerceiver(..., change_threshold, get_foreground)`、`set_summary(text, app="")`、`get_app()` はタスク間で一致。後方互換の既定値も一致。
