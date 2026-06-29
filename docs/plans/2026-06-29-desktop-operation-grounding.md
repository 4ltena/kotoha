# デスクトップ操作グラウンディング 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** つくよみが音声コマンドで画面を操作できるよう、キャプチャ→Holo2 グラウンディング→実行のループを安全機構ごと `kotoha/operate/` に実装する。

**Architecture:** 純ロジック（grounding パース・意図解析・ポリシー）と副作用（actuator）を分離し、`Operator` が会話前段プロバイダ（`api_search` 同型）として統合する。無害操作は単ターン即実行、破壊的操作は2ターン音声握手で確認する。設計の正は [docs/specs/2026-06-29-desktop-operation-grounding-design.md](../specs/2026-06-29-desktop-operation-grounding-design.md)。

**Tech Stack:** Python 3.11+, asyncio, aiohttp, 既存 `kotoha/llm/vlm_client.py`（`build_vlm_payload`/`parse_vlm_response` を再利用）、`kotoha/screen/capture.py`、PyAutoGUI/keyboard（遅延 import・rig のみ）。

## Global Constraints

- Python は `>=3.11`。ユニット検証は手元の 3.10 スクラッチ環境で行う（`str | None` 等は 3.10 で評価可能）。
- **この環境（開発機・macOS）は fake のみ**。モデル DL・実 grounding・実作動・`pyautogui`/`keyboard` の実 import はしない。実機部分は rig（RTX 4080 + Radeon VII）で integration テストと proof CLI に閉じる。
- 操作は best-effort。operator・actuator は会話ループへ例外を上げない。失敗は文脈文字列にして会話を続ける。
- 操作は既定 OFF のオプトイン（`operation_enabled=False`）。有効化しても既定 dry-run（`operation_dry_run=True`）。`operation_app_allowlist` が空なら全拒否。
- スクリーンショットはディスクへ保存しない。座標と短い結果文だけ残す。
- 重い依存（`pyautogui`/`keyboard`/`mss`/`PIL`）は関数・メソッド内で遅延 import する。
- ユニットテストは GPU・外部サービス・画面ハード・実入力なしで通す（fake 注入）。実機要は `@pytest.mark.integration` ＋ テスト内 `pytest.importorskip`。既定実行は `pytest -m "not integration"`。
- 座標形式: Holo2 は 0〜1000 正規化整数。逆写像は `abs = region原点 + norm/1000 × region実寸`。
- コミットは Conventional Commits。タイトルは英語。本文末尾に空行＋`Co-Authored-By: Claude <noreply@anthropic.com>`。author は既定の git 設定（`4ltena`）。

## ファイル構成

新規 `kotoha/operate/`:
- `__init__.py` — 空。
- `grounding.py` — `Region` / `GroundResult` / `parse_ground_response` / `map_norm_to_abs` / `ground_target`。
- `actions.py` — `ActionRequest` / `parse_intent` / `is_affirmative` / `is_negative`。
- `policy.py` — `is_destructive` / `app_allowed`。
- `actuator.py` — `Actuator`（副作用、fake backend 注入可）。
- `operator.py` — `Operator`（統合・確認待ち状態）。
- `stats.py` — `OperationStats`（観測専用）。
- `proof.py` — `run_proof` / `main`（proof CLI）。

既存への変更:
- `kotoha/config.py` — operation/grounding フィールド + `build_config` 配線。
- `.env.example` — 上書きキー追記。
- `kotoha/screen/capture.py` — `MssCapturer.capture_with_region`。
- `kotoha/orchestrator.py` — `operator=None` 注入と `handle_utterance` 呼び出し。
- `kotoha/local_app.py` — operate スタック構築とライフサイクル。
- `kotoha/diagnostics.py` — `diagnose_operation`。
- `kotoha/llm/persona.py` — 操作の振る舞いガイド。
- `pyproject.toml` — `[operate]` extra（`pyautogui` / `keyboard`）。

新規テスト: `tests/operate/{__init__,test_grounding,test_actions,test_policy,test_actuator,test_operator,test_stats,test_proof,test_integration}.py`、既存へ追記 `tests/test_config.py` / `tests/screen/test_capture.py` / `tests/test_orchestrator.py` / `tests/test_diagnostics.py`。

---

### Task 1: Config 拡張と build_config 配線

**Files:**
- Modify: `kotoha/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config` に operation/grounding フィールド。`build_config(env)` が `OPERATION_ENABLED`/`OPERATION_DRY_RUN`(bool)・`OPERATION_APP_ALLOWLIST`(tuple)・`GROUNDING_URL`/`GROUNDING_MODEL`/`GROUNDING_API`(str)・`GROUNDING_TIMEOUT_S`/`OPERATION_PENDING_TTL_S`(float) を読む。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config.py` に追記（無ければ新規。先頭に `from kotoha.config import Config, build_config`）。

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_config.py -k operation -v`
Expected: FAIL（`AttributeError: ... 'operation_enabled'`）

- [ ] **Step 3: Config フィールドを追加**

`kotoha/config.py` の `aux_llm_url` 行の直後（`@dataclass` の末尾フィールド）に追記。

```python
    # --- デスクトップ操作グラウンディング (docs/specs/2026-06-29-desktop-operation-grounding-design.md) ---
    operation_enabled: bool = False              # 既定OFFのオプトイン
    operation_dry_run: bool = True               # 既定は可視化のみ。falseで実作動(arming)
    operation_app_allowlist: tuple = ()          # 空=全拒否。許可する前面プロセス名
    operation_confirm_destructive: bool = True   # 破壊操作は2ターン音声確認
    operation_destructive_keywords: tuple = (
        "送信", "削除", "消", "購入", "買", "注文", "支払", "送金",
        "投稿", "公開", "閉じ", "破棄", "リセット", "フォーマット", "アンインストール",
    )
    operation_destructive_hotkeys_always: bool = True
    operation_kill_hotkey: str = "ctrl+alt+q"
    operation_max_actions_per_command: int = 1
    operation_pending_ttl_s: float = 60.0
    hotkey_map: tuple = (
        ("保存", "ctrl+s"), ("元に戻す", "ctrl+z"), ("コピー", "ctrl+c"),
        ("貼り付け", "ctrl+v"), ("全選択", "ctrl+a"),
    )
    grounding_url: str = ""                       # 空なら vlm_perception_url→ollama_url
    grounding_model: str = "holo2-8b"
    grounding_api: str = "openai"
    grounding_timeout_s: float = 30.0
    grounding_prompt: str = (
        "次の画面のスクリーンショットを見て、指示された UI 要素のクリック点を求めて。"
        "座標は画像に対して x, y それぞれ 0〜1000 で正規化した整数で 1 組だけ返す。"
    )
```

- [ ] **Step 4: build_config の env 配線を追加**

`_ENV_STR_FIELDS` のタプル末尾（`("KOTOHA_PLACE", "local_place"),` の後）に追記。

```python
    ("GROUNDING_URL", "grounding_url"),
    ("GROUNDING_MODEL", "grounding_model"),
    ("GROUNDING_API", "grounding_api"),
```

`build_config` の `flag = env.get("SCREEN_PERCEPTION_ENABLED")` ブロックの後、`return replace(...)` の前に追記。

```python
    for env_key, field in (("OPERATION_ENABLED", "operation_enabled"),
                           ("OPERATION_DRY_RUN", "operation_dry_run")):
        v = env.get(env_key)
        if v is not None and v != "":
            overrides[field] = v.strip().lower() in _TRUE
    allow = env.get("OPERATION_APP_ALLOWLIST")
    if allow is not None and allow != "":
        overrides["operation_app_allowlist"] = tuple(
            s.strip() for s in allow.split(",") if s.strip()
        )
    for env_key, field in (("GROUNDING_TIMEOUT_S", "grounding_timeout_s"),
                           ("OPERATION_PENDING_TTL_S", "operation_pending_ttl_s")):
        v = env.get(env_key)
        if v is not None and v != "":
            overrides[field] = float(v)
```

- [ ] **Step 5: .env.example に追記**

`.env.example` の末尾に追記。

```bash
# --- デスクトップ操作グラウンディング (既定OFF。実作動は3つの明示設定が必要) ---
# OPERATION_ENABLED=true
# OPERATION_DRY_RUN=false                 # arm: 可視化でなく実作動
# OPERATION_APP_ALLOWLIST=chrome.exe,code.exe   # 空=全拒否
# GROUNDING_URL=http://localhost:11436    # 空なら VLM_PERCEPTION_URL→OLLAMA_URL
# GROUNDING_MODEL=holo2-8b
```

- [ ] **Step 6: テストを実行して成功を確認**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: コミット**

```bash
git add kotoha/config.py .env.example tests/test_config.py
git commit -m "feat(operate): add operation and grounding config with env wiring

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: OperationStats（観測専用）

**Files:**
- Create: `kotoha/operate/__init__.py`（空）
- Create: `kotoha/operate/stats.py`
- Create: `tests/operate/__init__.py`（空）
- Test: `tests/operate/test_stats.py`

**Interfaces:**
- Produces: `OperationStats()`。`record(kind: str)`（kind: `"intents"|"grounded"|"executed"|"confirmed_pending"|"refused"|"expired"|"aborted"`）、`record_failure(kind: str)`、`record_ground_ms(ms: float)`、`snapshot() -> dict`、`summary_line() -> str`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_stats.py`:

```python
from kotoha.operate.stats import OperationStats


def test_counts_and_failures():
    s = OperationStats()
    s.record("intents")
    s.record("intents")
    s.record("grounded")
    s.record("executed")
    s.record("confirmed_pending")
    s.record_failure("ground")
    s.record_ground_ms(1200.0)
    s.record_ground_ms(800.0)
    snap = s.snapshot()
    assert snap["intents"] == 2
    assert snap["executed"] == 1
    assert snap["confirmed_pending"] == 1
    assert snap["failures"]["ground"] == 1
    assert snap["avg_ground_ms"] == 1000.0


def test_summary_line_is_human_readable():
    s = OperationStats()
    s.record("intents")
    s.record("executed")
    line = s.summary_line()
    assert "intents=1" in line and "exec=1" in line
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_stats.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.stats`）

- [ ] **Step 3: 実装する**

`kotoha/operate/__init__.py` と `tests/operate/__init__.py` を空で作成。`kotoha/operate/stats.py`:

```python
"""操作ループの計数とグラウンディングレイテンシをスレッドセーフに保持する観測専用オブジェクト。

会話にも操作判断にも影響しない。記録メソッドは例外を投げない。PerceptionStats と対称。
"""

import threading

_COUNTERS = ("intents", "grounded", "executed", "confirmed_pending",
             "refused", "expired", "aborted")


class OperationStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {k: 0 for k in _COUNTERS}
        self._failures = {}
        self._ground_ms_sum = 0.0
        self._ground_n = 0

    def record(self, kind: str) -> None:
        with self._lock:
            if kind in self._counts:
                self._counts[kind] += 1

    def record_failure(self, kind: str) -> None:
        with self._lock:
            self._failures[kind] = self._failures.get(kind, 0) + 1

    def record_ground_ms(self, ms: float) -> None:
        with self._lock:
            self._ground_ms_sum += ms
            self._ground_n += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg = self._ground_ms_sum / self._ground_n if self._ground_n else 0.0
            return {
                **dict(self._counts),
                "failures": dict(self._failures),
                "avg_ground_ms": avg,
            }

    def summary_line(self) -> str:
        s = self.snapshot()
        fails = sum(s["failures"].values())
        return (
            f"intents={s['intents']} grounded={s['grounded']} exec={s['executed']} "
            f"confirm={s['confirmed_pending']} refused={s['refused']} "
            f"aborted={s['aborted']} fail={fails}"
        )
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/operate/test_stats.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/__init__.py kotoha/operate/stats.py tests/operate/__init__.py tests/operate/test_stats.py
git commit -m "feat(operate): add OperationStats for operation-loop observability

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: grounding.py（Holo2 クライアントと座標写像）

**Files:**
- Create: `kotoha/operate/grounding.py`
- Test: `tests/operate/test_grounding.py`

**Interfaces:**
- Consumes: `build_vlm_payload` / `parse_vlm_response`（`kotoha/llm/vlm_client.py`）。
- Produces: `Region(left, top, width, height)`、`GroundResult(x, y, raw)`、`parse_ground_response(text) -> tuple[int,int] | None`（正規化 nx,ny）、`map_norm_to_abs(nx, ny, region) -> tuple[int,int]`、`async ground_target(image_b64, *, instruction, region, model, base_url, api="openai", session=None, timeout_s=30.0, prompt=...) -> GroundResult | None`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_grounding.py`:

```python
from kotoha.operate.grounding import (
    GroundResult, Region, ground_target, map_norm_to_abs, parse_ground_response,
)


def test_parse_strips_thinking_and_reads_click():
    text = "<think>左上のボタン…</think>\nclick(500, 250)"
    assert parse_ground_response(text) == (500, 250)


def test_parse_reads_bare_tuple_and_json_and_float():
    assert parse_ground_response("(120, 880)") == (120, 880)
    assert parse_ground_response('{"x": 10, "y": 20}') == (10, 20)
    assert parse_ground_response("click(512.6, 256.4)") == (513, 256)


def test_parse_rejects_out_of_range_and_missing():
    assert parse_ground_response("click(1200, 50)") is None
    assert parse_ground_response("見つかりません") is None
    assert parse_ground_response("") is None


def test_map_norm_to_abs_scales_and_clamps():
    r = Region(left=100, top=200, width=2000, height=1000)
    assert map_norm_to_abs(500, 500, r) == (1100, 700)
    assert map_norm_to_abs(1000, 1000, r) == (2099, 1199)   # 右下端へクランプ
    assert map_norm_to_abs(0, 0, Region(0, 0, 0, 0)) == (0, 0)   # ゼロ実寸ガード


async def test_ground_target_returns_mapped_result():
    class _Resp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def raise_for_status(self): pass
        async def json(self): return {"choices": [{"message": {"content": "click(500, 500)"}}]}

    class _Session:
        def post(self, url, **kw): return _Resp()

    r = await ground_target(
        "IMG", instruction="検索ボタン", region=Region(0, 0, 1000, 1000),
        model="holo2-8b", base_url="http://x", api="openai", session=_Session(),
    )
    assert isinstance(r, GroundResult) and (r.x, r.y) == (500, 500)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_grounding.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.grounding`）

- [ ] **Step 3: 実装する**

`kotoha/operate/grounding.py`:

```python
"""Holo2 グラウンディングクライアント。画像+指示→正規化座標→実OS座標へ写像する。

vlm_client の build_vlm_payload/parse_vlm_response を再利用する。Holo2 は
Qwen3-VL-8B-Thinking 由来で <think> を吐きうるので除去し、最終応答から座標を拾う。
失敗（接続不可・タイムアウト・パース不可）は None を返し例外を上げない（best-effort）。
"""

import logging
import re
from dataclasses import dataclass

import aiohttp

from kotoha.llm.vlm_client import build_vlm_payload, parse_vlm_response

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_NUM = r"(\d+(?:\.\d+)?)"
_PATTERNS = (
    re.compile(rf"click\(\s*{_NUM}\s*,\s*{_NUM}\s*\)", re.IGNORECASE),
    re.compile(rf"\(\s*{_NUM}\s*,\s*{_NUM}\s*\)"),
    re.compile(rf'"x"\s*:\s*{_NUM}.*?"y"\s*:\s*{_NUM}', re.DOTALL),
)

_DEFAULT_PROMPT = (
    "次の画面のスクリーンショットを見て、指示された UI 要素のクリック点を求めて。"
    "座標は画像に対して x, y それぞれ 0〜1000 で正規化した整数で 1 組だけ返す。"
)


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class GroundResult:
    x: int
    y: int
    raw: str


def parse_ground_response(text: str) -> "tuple[int, int] | None":
    """正規化座標 (nx, ny) を返す。<think> 除去→3段の正規表現→最初の一致のみ→範囲外は None。"""
    if not text:
        return None
    cleaned = _THINK_RE.sub("", text)
    for pat in _PATTERNS:
        m = pat.search(cleaned)
        if m:
            nx, ny = round(float(m.group(1))), round(float(m.group(2)))
            if 0 <= nx <= 1000 and 0 <= ny <= 1000:
                return (nx, ny)
            return None
    return None


def map_norm_to_abs(nx: int, ny: int, region: Region) -> "tuple[int, int]":
    """正規化 0〜1000 を region の実OS座標へ写像し、region 内へクランプする。"""
    if region.width <= 0 or region.height <= 0:
        return (region.left, region.top)
    x = region.left + round(nx / 1000 * region.width)
    y = region.top + round(ny / 1000 * region.height)
    x = max(region.left, min(region.left + region.width - 1, x))
    y = max(region.top, min(region.top + region.height - 1, y))
    return (x, y)


async def ground_target(
    image_b64: str,
    *,
    instruction: str,
    region: Region,
    model: str,
    base_url: str,
    api: str = "openai",
    session: "aiohttp.ClientSession | None" = None,
    timeout_s: float = 30.0,
    prompt: str = _DEFAULT_PROMPT,
) -> "GroundResult | None":
    """画像と指示を Holo2 へ送り GroundResult を返す。失敗は None（例外を上げない）。

    session=None のときは呼び出しごとに短命セッションを使い捨て、llama.cpp #17200
    （連続マルチモーダル要求の失敗）を回避する。
    """
    full_prompt = f"{prompt}\n対象: {instruction}"
    path, payload = build_vlm_payload(image_b64, prompt=full_prompt, model=model, api=api)
    own = session is None
    if own:
        session = aiohttp.ClientSession()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with session.post(f"{base_url}{path}", json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            obj = await resp.json()
        raw = parse_vlm_response(obj, api=api)
        norm = parse_ground_response(raw)
        if norm is None:
            return None
        x, y = map_norm_to_abs(norm[0], norm[1], region)
        return GroundResult(x=x, y=y, raw=raw)
    except Exception:
        logger.warning("grounding failed", exc_info=True)
        return None
    finally:
        if own:
            await session.close()
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/operate/test_grounding.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/grounding.py tests/operate/test_grounding.py
git commit -m "feat(operate): add Holo2 grounding client and coordinate mapping

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: actions.py（操作語彙と意図パース）

**Files:**
- Create: `kotoha/operate/actions.py`
- Test: `tests/operate/test_actions.py`

**Interfaces:**
- Produces: `ActionRequest(kind, target="", text="", keys="", amount=0)`、`parse_intent(text, *, config) -> ActionRequest | None`、`is_affirmative(text) -> bool`、`is_negative(text) -> bool`。config は `hotkey_map` を持つ（`Config` を渡す）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_actions.py`:

```python
from kotoha.config import Config
from kotoha.operate.actions import ActionRequest, is_affirmative, is_negative, parse_intent

CFG = Config()


def test_click_extracts_target():
    a = parse_intent("その検索ボタンをクリックして", config=CFG)
    assert a == ActionRequest(kind="click", target="その検索ボタン")


def test_demonstrative_only_target_is_blank():
    a = parse_intent("ここを押して", config=CFG)
    assert a.kind == "click" and a.target == ""


def test_right_click_before_click():
    a = parse_intent("そのファイルを右クリックして", config=CFG)
    assert a.kind == "right_click" and a.target == "そのファイル"


def test_double_click_on_open():
    a = parse_intent("そのフォルダを開いて", config=CFG)
    assert a.kind == "double_click" and a.target == "そのフォルダ"


def test_type_extracts_quoted_text():
    a = parse_intent("「こんにちは」と入力して", config=CFG)
    assert a.kind == "type" and a.text == "こんにちは"


def test_scroll_direction():
    assert parse_intent("下にスクロール", config=CFG).amount < 0
    assert parse_intent("上にスクロール", config=CFG).amount > 0


def test_hotkey_from_map():
    a = parse_intent("保存して", config=CFG)
    assert a.kind == "hotkey" and a.keys == "ctrl+s"


def test_no_intent_passes_through():
    assert parse_intent("今日は疲れたな", config=CFG) is None


def test_affirmative_and_negation_priority():
    assert is_affirmative("うん") is True
    assert is_negative("やめて") is True
    assert is_affirmative("そうじゃない") is False   # 否定優先
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_actions.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.actions`）

- [ ] **Step 3: 実装する**

`kotoha/operate/actions.py`:

```python
"""発話から操作意図を取り出す純ロジック。操作語が無ければ None で通常会話を素通しする。"""

import re
from dataclasses import dataclass

_DEMONSTRATIVES = ("ここ", "そこ", "あそこ", "これ", "それ", "あれ", "ここ")
_CLICK_WORDS = ("クリック", "押して", "選んで", "タップ")
_DOUBLE_WORDS = ("ダブルクリック", "開いて", "ひらいて")
_QUOTED = re.compile(r"[「『](.+?)[」』]")

_NEG_WORDS = ("やめ", "いや", "ちがう", "違う", "だめ", "じゃない", "しないで", "やだ", "キャンセル")
_AFF_WORDS = ("うん", "はい", "いいよ", "おねがい", "お願い", "そう", "やって", "オーケー", "ok")


@dataclass(frozen=True)
class ActionRequest:
    kind: str
    target: str = ""
    text: str = ""
    keys: str = ""
    amount: int = 0


def _extract_target(prefix: str) -> str:
    t = prefix.strip().strip("、。 　")
    for p in ("を", "の", "に", "へ"):
        if t.endswith(p):
            t = t[:-1]
    t = t.strip()
    if not t or t in _DEMONSTRATIVES:
        return ""
    return t[:30]


def _extract_type_text(s: str) -> str:
    m = _QUOTED.search(s)
    if m:
        return m.group(1).strip()[:200]
    idx = s.find("と入力")
    if idx > 0:
        return s[:idx].strip()[:200]
    idx = s.find("入力")
    if idx > 0:
        return s[:idx].strip().rstrip("をに").strip()[:200]
    return ""


def parse_intent(text, *, config) -> "ActionRequest | None":
    s = text.strip()
    if "右クリック" in s:
        return ActionRequest("right_click", target=_extract_target(s.split("右クリック")[0]))
    if "スクロール" in s or "ページアップ" in s or "ページダウン" in s:
        up = ("上" in s) or ("ページアップ" in s)
        return ActionRequest("scroll", amount=5 if up else -5)
    for word, combo in config.hotkey_map:
        if word in s:
            return ActionRequest("hotkey", keys=combo)
    if "入力" in s:
        body = _extract_type_text(s)
        return ActionRequest("type", text=body) if body else None
    for w in _DOUBLE_WORDS:
        if w in s:
            return ActionRequest("double_click", target=_extract_target(s.split(w)[0]))
    for w in _CLICK_WORDS:
        if w in s:
            return ActionRequest("click", target=_extract_target(s.split(w)[0]))
    return None


def is_negative(text) -> bool:
    s = (text or "").strip().lower()
    return any(w in s for w in _NEG_WORDS)


def is_affirmative(text) -> bool:
    s = (text or "").strip().lower()
    if is_negative(s):
        return False
    return any(w in s for w in _AFF_WORDS)
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/operate/test_actions.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/actions.py tests/operate/test_actions.py
git commit -m "feat(operate): add intent parsing for operation vocabulary

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: policy.py（破壊分類と allowlist）

**Files:**
- Create: `kotoha/operate/policy.py`
- Test: `tests/operate/test_policy.py`

**Interfaces:**
- Consumes: `ActionRequest`（Task 4）。
- Produces: `is_destructive(action, *, destructive_keywords, hotkeys_always) -> bool`、`app_allowed(foreground_process, *, allowlist) -> bool`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_policy.py`:

```python
from kotoha.operate.actions import ActionRequest
from kotoha.operate.policy import app_allowed, is_destructive

KW = ("送信", "削除")


def test_destructive_by_keyword():
    a = ActionRequest("click", target="送信ボタン")
    assert is_destructive(a, destructive_keywords=KW, hotkeys_always=True) is True


def test_hotkey_always_destructive():
    a = ActionRequest("hotkey", keys="ctrl+s")
    assert is_destructive(a, destructive_keywords=(), hotkeys_always=True) is True


def test_harmless_click_not_destructive():
    a = ActionRequest("click", target="検索ボタン")
    assert is_destructive(a, destructive_keywords=KW, hotkeys_always=True) is False


def test_empty_allowlist_denies_all():
    assert app_allowed("chrome.exe", allowlist=()) is False


def test_allowlist_basename_lowercase_match():
    assert app_allowed("C:\\\\Program Files\\\\Chrome.exe", allowlist=("chrome.exe",)) is True
    assert app_allowed("/usr/bin/code", allowlist=("code",)) is True
    assert app_allowed("notepad.exe", allowlist=("chrome.exe",)) is False
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_policy.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.policy`）

- [ ] **Step 3: 実装する**

`kotoha/operate/policy.py`:

```python
"""操作の安全ポリシー判定（純関数）。破壊的かどうかと、前面アプリが許可されているか。"""


def is_destructive(action, *, destructive_keywords, hotkeys_always) -> bool:
    """破壊的なら True。hotkey は hotkeys_always で常に True。保守的に過剰確認側へ倒す。"""
    if action.kind == "hotkey" and hotkeys_always:
        return True
    hay = (action.target + " " + action.text).lower()
    return any(kw.lower() in hay for kw in destructive_keywords)


def app_allowed(foreground_process, *, allowlist) -> bool:
    """allowlist が空なら全拒否。非空なら前面プロセスの basename 小文字完全一致で判定。"""
    if not allowlist:
        return False
    name = (foreground_process or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    return name in {a.lower() for a in allowlist}
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/operate/test_policy.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/policy.py tests/operate/test_policy.py
git commit -m "feat(operate): add destructive classification and app allowlist policy

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: actuator.py（副作用層・FAILSAFE・kill・dry-run）

**Files:**
- Create: `kotoha/operate/actuator.py`
- Modify: `pyproject.toml`
- Test: `tests/operate/test_actuator.py`

**Interfaces:**
- Consumes: `ActionRequest`（Task 4）。
- Produces: `Actuator(*, dry_run, kill_hotkey, max_actions, backend=None)`、`execute(action, *, coords) -> bool`、`aborted() -> bool`、`kill_available() -> bool`、`is_dry_run() -> bool`、`reset()`、`close()`。backend は `click(x,y)/double_click(x,y)/right_click(x,y)/type_text(text)/scroll(amount)/hotkey(keys)` を持つダックタイプ。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_actuator.py`:

```python
from kotoha.operate.actions import ActionRequest
from kotoha.operate.actuator import Actuator


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def click(self, x, y): self.calls.append(("click", x, y))
    def double_click(self, x, y): self.calls.append(("double_click", x, y))
    def right_click(self, x, y): self.calls.append(("right_click", x, y))
    def type_text(self, t): self.calls.append(("type", t))
    def scroll(self, n): self.calls.append(("scroll", n))
    def hotkey(self, k): self.calls.append(("hotkey", k))


def test_dry_run_does_not_touch_backend():
    b = _FakeBackend()
    act = Actuator(dry_run=True, kill_hotkey="ctrl+alt+q", max_actions=1, backend=b)
    assert act.execute(ActionRequest("type", text="x"), coords=None) is True
    assert b.calls == []   # 実入力されない


def test_real_mode_calls_backend():
    b = _FakeBackend()
    act = Actuator(dry_run=False, kill_hotkey="ctrl+alt+q", max_actions=2, backend=b)
    assert act.execute(ActionRequest("click"), coords=(10, 20)) is True
    assert b.calls == [("click", 10, 20)]


def test_max_actions_caps():
    b = _FakeBackend()
    act = Actuator(dry_run=False, kill_hotkey="ctrl+alt+q", max_actions=1, backend=b)
    act.execute(ActionRequest("click"), coords=(1, 1))
    assert act.execute(ActionRequest("click"), coords=(2, 2)) is False


def test_kill_aborts():
    b = _FakeBackend()
    act = Actuator(dry_run=False, kill_hotkey="ctrl+alt+q", max_actions=5, backend=b)
    act._aborted = True
    assert act.execute(ActionRequest("click"), coords=(1, 1)) is False
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_actuator.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.actuator`）

- [ ] **Step 3: 実装する**

`kotoha/operate/actuator.py`:

```python
"""マウス・キーボードの実行層。dry-run は全 kind の実副作用を抑止する。

backend is None（実モード）のときだけ pyautogui を import して FAILSAFE を立て、
keyboard でグローバル kill ホットキーを登録する。テストは fake backend を注入し、
pyautogui/keyboard を一切 import しない。例外・FAILSAFE・kill は全て握って False を返す。
"""

import logging

logger = logging.getLogger(__name__)


def _describe_action(action, coords) -> str:
    k = action.kind
    if k in ("click", "double_click", "right_click"):
        return f"{k} {coords}"
    if k == "type":
        return f"type 「{action.text}」"
    if k == "scroll":
        return f"scroll {action.amount}"
    if k == "hotkey":
        return f"hotkey {action.keys}"
    return k


class _PyAutoGuiBackend:
    def __init__(self):
        import pyautogui   # 遅延 import
        pyautogui.FAILSAFE = True
        self._pg = pyautogui

    def click(self, x, y): self._pg.click(x, y)
    def double_click(self, x, y): self._pg.doubleClick(x, y)
    def right_click(self, x, y): self._pg.rightClick(x, y)

    def type_text(self, text):
        import keyboard   # unicode 入力は keyboard.write が確実
        keyboard.write(text)

    def scroll(self, amount): self._pg.scroll(amount)

    def hotkey(self, keys):
        import keyboard
        keyboard.send(keys)


class Actuator:
    def __init__(self, *, dry_run, kill_hotkey, max_actions, backend=None):
        self._dry_run = dry_run
        self._kill_hotkey = kill_hotkey
        self._max_actions = max_actions
        self._aborted = False
        self._kill_available = False
        self._count = 0
        self._keyboard = None
        if backend is not None:
            self._backend = backend
            return
        self._backend = _PyAutoGuiBackend()   # 実モードでのみ pyautogui を掴む
        try:
            import keyboard
            keyboard.add_hotkey(kill_hotkey, self._on_kill)
            self._keyboard = keyboard
            self._kill_available = True
        except Exception:
            logger.warning(
                "kill hotkey registration failed (permission/dep?); FAILSAFE-only",
                exc_info=True,
            )

    def _on_kill(self):
        self._aborted = True

    def aborted(self) -> bool:
        return self._aborted

    def kill_available(self) -> bool:
        return self._kill_available

    def is_dry_run(self) -> bool:
        return self._dry_run

    def reset(self) -> None:
        self._aborted = False
        self._count = 0

    def execute(self, action, *, coords) -> bool:
        if self._aborted or self._count >= self._max_actions:
            return False
        self._count += 1
        try:
            if self._dry_run:
                logger.info("[dry-run] %s", _describe_action(action, coords))
                return True
            return self._do(action, coords)
        except Exception:
            logger.warning("actuation failed", exc_info=True)
            return False

    def _do(self, action, coords) -> bool:
        b = self._backend
        k = action.kind
        if k == "click":
            b.click(coords[0], coords[1])
        elif k == "double_click":
            b.double_click(coords[0], coords[1])
        elif k == "right_click":
            b.right_click(coords[0], coords[1])
        elif k == "type":
            b.type_text(action.text)
        elif k == "scroll":
            b.scroll(action.amount)
        elif k == "hotkey":
            b.hotkey(action.keys)
        else:
            return False
        return True

    def close(self) -> None:
        if self._keyboard is not None:
            try:
                self._keyboard.remove_hotkey(self._kill_hotkey)
            except Exception:
                logger.warning("kill hotkey removal failed", exc_info=True)
```

- [ ] **Step 4: pyproject に extra を追加**

`pyproject.toml` の `[project.optional-dependencies]` に追記（無ければ作る。rig のみ導入、ユニットは fake で不要）。

```toml
operate = ["pyautogui", "keyboard"]
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `pytest tests/operate/test_actuator.py -v`
Expected: PASS（fake backend のみ。pyautogui/keyboard は import されない）

- [ ] **Step 6: コミット**

```bash
git add kotoha/operate/actuator.py pyproject.toml tests/operate/test_actuator.py
git commit -m "feat(operate): add actuator with dry-run, FAILSAFE, and kill switch

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: operator.py（統合と確認待ち状態）

**Files:**
- Create: `kotoha/operate/operator.py`
- Test: `tests/operate/test_operator.py`

**Interfaces:**
- Consumes: `parse_intent`/`is_affirmative`/`is_negative`（Task 4）、`is_destructive`/`app_allowed`（Task 5）、`OperationStats`（Task 2）、`ground_target`/`Region`/`GroundResult`（Task 3）、`Actuator`（Task 6）。
- Produces: `Operator(*, ground, capture_region, actuator, policy_cfg, get_foreground, stats=None, confirm_destructive=True, pending_ttl_s=60.0, clock=time.monotonic)`、`async handle(text, *, user_id=None) -> str | None`。`policy_cfg` は `Config`（`hotkey_map`/`operation_app_allowlist`/`operation_destructive_keywords`/`operation_destructive_hotkeys_always` を読む）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_operator.py`:

```python
from kotoha.config import Config
from kotoha.operate.actions import ActionRequest
from kotoha.operate.grounding import GroundResult, Region
from kotoha.operate.operator import Operator

CFG = Config(operation_app_allowlist=("chrome.exe",))


class _Actuator:
    def __init__(self, dry=False):
        self.executed = []
        self._dry = dry
        self._aborted = False

    def execute(self, action, *, coords):
        self.executed.append((action.kind, coords))
        return True

    def aborted(self): return self._aborted
    def is_dry_run(self): return self._dry


def _ground_ok(image_b64, *, instruction, region):
    return GroundResult(x=100, y=200, raw="click(100,200)")


def _cap():
    return ("IMG", Region(0, 0, 1000, 1000))


def _op(actuator, *, fg="chrome.exe", ground=_ground_ok, confirm=True):
    return Operator(
        ground=ground, capture_region=_cap, actuator=actuator, policy_cfg=CFG,
        get_foreground=lambda: fg, confirm_destructive=confirm,
    )


async def test_passthrough_when_no_intent():
    assert await _op(_Actuator()).handle("今日は疲れたな", user_id=0) is None


async def test_harmless_executes_immediately():
    act = _Actuator()
    out = await _op(act).handle("その検索ボタンをクリックして", user_id=0)
    assert act.executed == [("click", (100, 200))]
    assert "クリック" in out or "した" in out


async def test_destructive_asks_then_executes_on_yes():
    act = _Actuator()
    op = _op(act)
    first = await op.handle("送信ボタンをクリックして", user_id=0)
    assert act.executed == []            # 確認待ちで未実行
    assert "確認" in first
    second = await op.handle("うん", user_id=0)
    assert act.executed == [("click", (100, 200))]


async def test_destructive_cancelled_on_no():
    act = _Actuator()
    op = _op(act)
    await op.handle("送信ボタンをクリックして", user_id=0)
    out = await op.handle("やめて", user_id=0)
    assert act.executed == [] and "取りやめ" in out


async def test_allowlist_blocks():
    act = _Actuator()
    out = await _op(act, fg="evil.exe").handle("その検索ボタンをクリックして", user_id=0)
    assert act.executed == [] and "許可外" in out


async def test_confirm_rechecks_allowlist_on_app_change():
    act = _Actuator()
    fg = {"name": "chrome.exe"}
    op = Operator(
        ground=_ground_ok, capture_region=_cap, actuator=act, policy_cfg=CFG,
        get_foreground=lambda: fg["name"],
    )
    await op.handle("送信ボタンをクリックして", user_id=0)
    fg["name"] = "evil.exe"             # 確認の間にアプリが変わる
    out = await op.handle("うん", user_id=0)
    assert act.executed == [] and "変わった" in out


async def test_grounding_failure_reports():
    act = _Actuator()
    out = await _op(act, ground=lambda *a, **k: None).handle(
        "その検索ボタンをクリックして", user_id=0)
    assert act.executed == [] and out.startswith("[操作失敗]")
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_operator.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.operator`）

- [ ] **Step 3: 実装する**

`kotoha/operate/operator.py`:

```python
"""操作の統合中核。会話前段プロバイダとして注入され、確認待ち状態をターン跨ぎで保持する。

handle が返す文字列を orchestrator が system メッセージへ注入する。操作意図が無ければ
None。best-effort で例外を声ループへ上げない。直列化されたターン処理内でのみ呼ばれる。
"""

import logging
import time

from kotoha.operate.actions import is_affirmative, is_negative, parse_intent
from kotoha.operate.policy import app_allowed, is_destructive

logger = logging.getLogger(__name__)

_FAIL = "[操作失敗] "
_NEEDS_GROUND = ("click", "double_click", "right_click")


def _confirm_prompt(action) -> str:
    what = action.target or {"type": "入力", "hotkey": action.keys}.get(action.kind, "操作")
    return f"{what}の操作を求めている。実行前に確認する"


def _result_text(action, *, dry_run) -> str:
    label = action.target or action.text or action.keys or action.kind
    if dry_run:
        return f"（dry-run: {label} を操作するところ。実際にはしていない）"
    return f"（{label} を操作した）"


class Operator:
    def __init__(self, *, ground, capture_region, actuator, policy_cfg, get_foreground,
                 stats=None, confirm_destructive=True, pending_ttl_s=60.0, clock=time.monotonic):
        self._ground = ground
        self._capture_region = capture_region
        self._actuator = actuator
        self._cfg = policy_cfg
        self._get_foreground = get_foreground
        self._stats = stats
        self._confirm = confirm_destructive
        self._ttl = pending_ttl_s
        self._clock = clock
        self._pending = {}   # user_id -> (ActionRequest, ts)

    def _rec(self, kind):
        if self._stats is not None:
            self._stats.record(kind)

    def _fail(self, kind, msg):
        if self._stats is not None:
            self._stats.record_failure(kind)
        return _FAIL + msg

    async def handle(self, text, *, user_id=None) -> "str | None":
        try:
            return await self._handle(text, user_id)
        except Exception:
            logger.warning("operator.handle crashed; treating as no-op", exc_info=True)
            return None

    async def _handle(self, text, user_id):
        pend = self._pending.get(user_id)
        if pend is not None and self._clock() - pend[1] > self._ttl:
            del self._pending[user_id]
            self._rec("expired")
            pend = None
        if pend is not None:
            if is_negative(text):
                del self._pending[user_id]
                self._rec("refused")
                return "操作を取りやめた"
            if is_affirmative(text):
                action, _ = pend
                del self._pending[user_id]
                if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
                    return "対象アプリが変わったため取りやめた"
                return await self._run(action)
            del self._pending[user_id]   # 肯定でも否定でもない: 破棄して新意図へ

        action = parse_intent(text, config=self._cfg)
        if action is None:
            return None
        self._rec("intents")
        if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
            return self._fail("allowlist", "許可外アプリ")
        if self._confirm and is_destructive(
            action,
            destructive_keywords=self._cfg.operation_destructive_keywords,
            hotkeys_always=self._cfg.operation_destructive_hotkeys_always,
        ):
            self._pending[user_id] = (action, self._clock())
            self._rec("confirmed_pending")
            return _confirm_prompt(action)
        return await self._run(action)

    async def _run(self, action):
        cap = None
        try:
            cap = self._capture_region()
        except Exception:
            cap = None
        if not cap:
            return self._fail("capture", "キャプチャ失敗")
        image_b64, region = cap
        coords = None
        if action.kind in _NEEDS_GROUND:
            t0 = self._clock()
            result = await self._ground(image_b64, instruction=action.target or action.kind, region=region)
            if self._stats is not None:
                self._stats.record_ground_ms((self._clock() - t0) * 1000)
            if result is None:
                return self._fail("ground", "対象が見つからない")
            self._rec("grounded")
            coords = (result.x, result.y)
        ok = self._actuator.execute(action, coords=coords)
        if self._actuator.aborted():
            self._rec("aborted")
            return _FAIL + "中止(kill)"
        if not ok:
            return self._fail("execute", "実行できなかった")
        self._rec("executed")
        return _result_text(action, dry_run=self._actuator.is_dry_run())
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/operate/test_operator.py -v`
Expected: PASS

- [ ] **Step 5: 全体テストで回帰なしを確認**

Run: `pytest -m "not integration" -q`
Expected: 既存＋新規がすべて PASS

- [ ] **Step 6: コミット**

```bash
git add kotoha/operate/operator.py tests/operate/test_operator.py
git commit -m "feat(operate): add Operator integrating grounding, policy, and actuation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: capture_with_region（MssCapturer 拡張）

**Files:**
- Modify: `kotoha/screen/capture.py`
- Test: `tests/screen/test_capture.py`

**Interfaces:**
- Consumes: `Region`（Task 3）、既存 `encode_frame`。
- Produces: `MssCapturer.capture_with_region(self) -> tuple[str, Region] | None`。縮小済み base64 とプライマリモニタの実矩形を返す。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_capture.py` に追記。

```python
def test_capture_with_region_maps_monitor(monkeypatch):
    from kotoha.operate.grounding import Region
    from kotoha.screen.capture import MssCapturer

    cap = MssCapturer(max_long_edge=1024)

    class _Raw:
        size = (200, 100)
        rgb = b"\\x00" * (200 * 100 * 3)

    class _Sct:
        monitors = [None, {"left": 10, "top": 20, "width": 200, "height": 100}]
        def grab(self, mon): return _Raw()

    cap._sct = _Sct()
    monkeypatch.setattr(cap, "_ensure", lambda: None)
    img_b64, region = cap.capture_with_region()
    assert isinstance(img_b64, str) and img_b64
    assert region == Region(left=10, top=20, width=200, height=100)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_capture.py -k region -v`
Expected: FAIL（`AttributeError: ... 'capture_with_region'`）

- [ ] **Step 3: 実装する**

`kotoha/screen/capture.py` の `MssCapturer.capture` メソッドの直後に追記。

```python
    def capture_with_region(self):
        """縮小済み base64 とプライマリモニタの実矩形 Region を返す。失敗は None。

        操作グラウンディングの座標写像に使う。操作機能は screen_capture_backend に
        よらず常に mss プライマリで撮る（DxcamCapturer は region 同定を持たない）。
        """
        try:
            from PIL import Image   # 遅延 import
            from kotoha.operate.grounding import Region
            self._ensure()
            mon = self._sct.monitors[1]
            raw = self._sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            b64 = encode_frame(img, max_long_edge=self._max_long_edge)
            region = Region(left=mon["left"], top=mon["top"],
                            width=mon["width"], height=mon["height"])
            return b64, region
        except Exception:
            logger.warning("mss capture_with_region failed", exc_info=True)
            return None
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_capture.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/capture.py tests/screen/test_capture.py
git commit -m "feat(screen): add capture_with_region for operation coordinate mapping

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: orchestrator への operator 注入

**Files:**
- Modify: `kotoha/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Operator.handle(text, *, user_id)`（Task 7）。
- Produces: `Orchestrator(..., operator=None)`。`handle_utterance` が `await self.operator.handle(text, user_id=user_id)` を呼び、非 None を system メッセージへ注入する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_orchestrator.py` に追記（既存のヘルパ・fake を流用。下は最小の独立テスト）。

```python
async def test_operator_context_injected_before_llm():
    import numpy as np
    from kotoha.llm import persona
    from kotoha.orchestrator import Orchestrator

    captured = []

    def llm(messages, *, model):
        captured.append([dict(m) for m in messages])

        async def gen():
            yield "はい。"
        return gen()

    async def tts(text): return b""

    class _Tr:
        def transcribe(self, audio): return "その検索ボタンをクリックして"

    class _Player:
        def is_playing(self): return False
        def stop(self): pass
        async def play_and_wait(self, wav): return True

    class _Op:
        async def handle(self, text, *, user_id):
            return "（検索ボタンを操作した）"

    orch = Orchestrator(
        transcriber=_Tr(), llm_stream=llm, tts=tts, player=_Player(),
        model="m", vad_factory=lambda: object(), persona=persona, operator=_Op(),
    )
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    sys_contents = [m["content"] for m in captured[0] if m["role"] == "system"]
    assert any("検索ボタンを操作した" in c for c in sys_contents)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_orchestrator.py -k operator -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'operator'`）

- [ ] **Step 3: __init__ に operator を追加**

`kotoha/orchestrator.py` の `__init__` 署名、`screen_context=None,` の後に追記。

```python
        operator=None,
```

`__init__` 本体、`self._screen_context = screen_context` の行の後に追記。

```python
        self.operator = operator   # 操作グラウンディング前段プロバイダ(任意)
```

- [ ] **Step 4: handle_utterance に注入を追加**

`handle_utterance` の画面知覚注入ブロック（`if self._screen_context is not None:` 〜 注入）の直後に追記。

```python
        # 操作グラウンディング: 前段で意図を解釈・実行し、結果文脈を注入する(best-effort・任意)。
        if self.operator is not None:
            try:
                op_ctx = await self.operator.handle(text, user_id=user_id)
            except Exception:
                logger.exception("operator failed")
                op_ctx = None
            if op_ctx:
                logger.info("operation: %s", op_ctx)
                messages.insert(-1, {
                    "role": "system",
                    "content": (
                        "【画面操作の結果】\n" + op_ctx
                        + "\nこの結果を踏まえ、操作の成否を短く自然に伝える。失敗なら必ずそれを伝える。"
                    ),
                })
```

- [ ] **Step 5: テストを実行して成功を確認**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS（既存テストも緑）

- [ ] **Step 6: コミット**

```bash
git add kotoha/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): inject operator result as pre-LLM context

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: local_app 配線・diagnostics・persona

**Files:**
- Modify: `kotoha/local_app.py`
- Modify: `kotoha/diagnostics.py`
- Modify: `kotoha/llm/persona.py`
- Test: `tests/test_diagnostics.py`, `tests/operate/test_persona_guidance.py`

**Interfaces:**
- Consumes: `Operator`/`Actuator`/`ground_target`/`OperationStats`、`probe_llm_endpoint`（`kotoha/health.py`）。
- Produces: `local_app` が `operation_enabled` のとき operate スタックを構築し orchestrator へ渡す。`diagnostics.diagnose_operation(config, *, session, foreground_probe=None) -> dict | None`。

- [ ] **Step 1: diagnostics の失敗するテストを書く**

`tests/test_diagnostics.py` に追記。

```python
async def test_diagnose_operation_none_when_disabled():
    from kotoha.config import Config
    from kotoha.diagnostics import diagnose_operation

    class _OkSession:
        def get(self, url):
            class _R:
                status = 200
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return False
            return _R()

    cfg = Config(operation_enabled=False)
    assert await diagnose_operation(cfg, session=_OkSession()) is None


async def test_diagnose_operation_reports_when_enabled():
    from kotoha.config import Config
    from kotoha.diagnostics import diagnose_operation

    class _OkSession:
        def get(self, url):
            class _R:
                status = 200
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return False
            return _R()

    cfg = Config(operation_enabled=True, grounding_api="ollama")
    result = await diagnose_operation(
        cfg, session=_OkSession(), foreground_probe=lambda: "chrome.exe")
    assert result["grounding_ok"] is True
    assert result["foreground_ok"] is True
    assert result["dry_run"] is True
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_diagnostics.py -k operation -v`
Expected: FAIL（`ImportError: cannot import name 'diagnose_operation'`）

- [ ] **Step 3: diagnose_operation を実装する**

`kotoha/diagnostics.py` の `diagnose_screen` 関数の直後に追記。

```python
async def diagnose_operation(config, *, session, foreground_probe=None) -> dict | None:
    """操作レディネスを返す。無効なら None。grounding 到達・前面取得・dry-run 状態を見る。"""
    if not getattr(config, "operation_enabled", False):
        return None
    g_url = config.grounding_url or config.vlm_perception_url or config.ollama_url
    grounding_ok = await probe_llm_endpoint(session, g_url, api=config.grounding_api)
    if foreground_probe is None:
        def foreground_probe():
            from kotoha.screen.detector import get_foreground_info
            return get_foreground_info()
    try:
        foreground_ok = bool(foreground_probe())
    except Exception:
        foreground_ok = False
    return {
        "grounding_url": g_url,
        "grounding_ok": grounding_ok,
        "foreground_ok": foreground_ok,
        "dry_run": config.operation_dry_run,
        "allowlist": config.operation_app_allowlist,
    }
```

`run_diagnostics` の `screen = await diagnose_screen(config, session=session)` の直後に追記。

```python
        operation = await diagnose_operation(config, session=session)
```

`run_diagnostics` の screen 表示ブロックの後に追記。

```python
    if operation is not None:
        armed = "ARMED" if not operation["dry_run"] else "dry-run"
        print(f"[operate]   grounding({operation['grounding_url']}): "
              f"{'OK' if operation['grounding_ok'] else 'DOWN'}, "
              f"foreground: {'OK' if operation['foreground_ok'] else 'FAIL'}, "
              f"{armed}, allowlist={operation['allowlist'] or '(empty=deny all)'}")
```

- [ ] **Step 4: 診断テストを実行して成功を確認**

Run: `pytest tests/test_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: persona の失敗するテストを書く**

`tests/operate/test_persona_guidance.py`:

```python
from kotoha.llm import persona


def test_persona_mentions_operation_behavior():
    p = persona.SYSTEM_PROMPT
    assert "操作" in p and "確認" in p and "失敗" in p
```

- [ ] **Step 6: persona にガイドを追加**

`kotoha/llm/persona.py` の `STYLE_PROMPT` の末尾要素（`"「画面の様子」が示されたら…"` の文字列）の直後に文字列を追記。

```python
    "頼まれたら画面を操作できる。破壊的な操作は実行前に確認し、操作したら短く報告する。"
    "操作が失敗したときは必ずそれを伝える。頼まれていないのに勝手に操作しない。"
```

- [ ] **Step 7: local_app に operate スタックを配線する**

`kotoha/local_app.py` の import 群に追記。

```python
from kotoha.operate.actuator import Actuator
from kotoha.operate.grounding import ground_target
from kotoha.operate.operator import Operator
from kotoha.operate.stats import OperationStats
```

`run_local` の画面知覚ブロック（`screen_tasks` 構築）の後、`Orchestrator(...)` 構築より前に追記。

```python
        operator = None
        operation_stats = None
        if config.operation_enabled:
            import functools
            operation_stats = OperationStats()
            g_url = config.grounding_url or config.vlm_perception_url or config.ollama_url
            ground = functools.partial(
                ground_target, model=config.grounding_model, base_url=g_url,
                api=config.grounding_api, session=None,
                timeout_s=config.grounding_timeout_s, prompt=config.grounding_prompt,
            )
            op_capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)
            actuator = Actuator(
                dry_run=config.operation_dry_run,
                kill_hotkey=config.operation_kill_hotkey,
                max_actions=config.operation_max_actions_per_command,
            )
            from kotoha.screen.detector import get_foreground_info
            operator = Operator(
                ground=ground, capture_region=op_capturer.capture_with_region,
                actuator=actuator, policy_cfg=config,
                get_foreground=lambda: (get_foreground_info() or {}).get("process", ""),
                stats=operation_stats, confirm_destructive=config.operation_confirm_destructive,
                pending_ttl_s=config.operation_pending_ttl_s,
            )
            armed = "ARMED" if not config.operation_dry_run else "dry-run"
            print(f"[operate] enabled (grounding={config.grounding_model}, {armed}, "
                  f"allowlist={config.operation_app_allowlist or '(empty=deny all)'})")
```

`Orchestrator(...)` 呼び出しへ `operator=operator,` を追加する（`screen_context=screen_ctx,` の近く）。

`run_local` の `finally` ブロック、`if screen_stats is not None:` の後に追記。

```python
            if operator is not None:
                actuator.close()
            if operation_stats is not None:
                print("[operate] stats: " + operation_stats.summary_line())
```

- [ ] **Step 8: 全体テストを実行**

Run: `pytest -m "not integration" -q`
Expected: 既存＋新規がすべて PASS（回帰なし）

- [ ] **Step 9: コミット**

```bash
git add kotoha/local_app.py kotoha/diagnostics.py kotoha/llm/persona.py tests/test_diagnostics.py tests/operate/test_persona_guidance.py
git commit -m "feat(operate): wire operator stack, diagnostics, and persona guidance

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: proof CLI（`python -m kotoha.operate.proof`）

**Files:**
- Create: `kotoha/operate/proof.py`
- Test: `tests/operate/test_proof.py`

**Interfaces:**
- Consumes: `build_config`、`ground_target`/`Region`、`MssCapturer`、`Actuator`、`get_foreground_info`。
- Produces: `async run_proof(*, instruction, capture_region, ground, actuator, out=print) -> None`（テスト可能な中核）、`main(argv=None) -> int`（実機結線、`--arm` で実作動）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/operate/test_proof.py`:

```python
from kotoha.operate.grounding import GroundResult, Region
from kotoha.operate.proof import run_proof


class _Act:
    def __init__(self): self.calls = []
    def execute(self, action, *, coords): self.calls.append(coords); return True
    def aborted(self): return False
    def is_dry_run(self): return True


async def test_run_proof_prints_region_and_coords():
    def cap(): return ("IMG", Region(0, 0, 1000, 1000))

    async def ground(image_b64, *, instruction, region):
        return GroundResult(x=500, y=250, raw="click(500,250)")

    lines = []
    await run_proof(instruction="検索ボタン", capture_region=cap, ground=ground,
                    actuator=_Act(), out=lines.append)
    text = "\n".join(lines)
    assert "[region]" in text and "[abs] 500,250" in text
    assert "COORDINATE_FORMAT" in text
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/operate/test_proof.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.operate.proof`）

- [ ] **Step 3: 実装する**

`kotoha/operate/proof.py`:

```python
"""操作グラウンディングだけを単体起動して目視確認する proof CLI。

GPT-SoVITS とマイクには触れない。指定の指示を実画面でグラウンディングして、前面アプリ・
region・正規化/絶対座標・dry-run の「ここを押す」を表示する。`--arm` で初めて実作動する。
Holo2 の実座標出力形式（0〜1000 正規化）の裏取りにも使う。`python -m kotoha.operate.proof "指示"`。
"""

import argparse
import asyncio
import functools

from kotoha.config import build_config
from kotoha.operate.actions import ActionRequest
from kotoha.operate.actuator import Actuator
from kotoha.operate.grounding import ground_target


async def run_proof(*, instruction, capture_region, ground, actuator, out=print) -> None:
    """1 指示をグラウンディングして region・座標・実行結果を表示する（実機/テスト共用）。"""
    cap = capture_region()
    if not cap:
        out("[capture] FAILED")
        return
    image_b64, region = cap
    out(f"[region] {region.left},{region.top},{region.width},{region.height}")
    result = await ground(image_b64, instruction=instruction, region=region)
    if result is None:
        out("[ground] no coordinates")
        return
    out(f"[abs] {result.x},{result.y}")
    out(f"[raw] {result.raw!r}")
    out("COORDINATE_FORMAT: 0-1000 normalized (assumed) — verify against raw above")
    ok = actuator.execute(ActionRequest("click", target=instruction), coords=(result.x, result.y))
    mode = "dry-run" if actuator.is_dry_run() else "ARMED"
    out(f"[execute:{mode}] ok={ok}")


async def _main(args) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    config = build_config()
    from kotoha.screen.capture import MssCapturer
    from kotoha.screen.detector import get_foreground_info
    capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)
    g_url = config.grounding_url or config.vlm_perception_url or config.ollama_url
    print(f"[foreground] {get_foreground_info()}")
    print(f"[grounding] model={config.grounding_model} url={g_url} api={config.grounding_api}")
    ground = functools.partial(
        ground_target, model=config.grounding_model, base_url=g_url,
        api=config.grounding_api, session=None,
        timeout_s=config.grounding_timeout_s, prompt=config.grounding_prompt,
    )
    actuator = Actuator(
        dry_run=not args.arm, kill_hotkey=config.operation_kill_hotkey,
        max_actions=config.operation_max_actions_per_command,
    )
    try:
        await run_proof(instruction=args.instruction, capture_region=capturer.capture_with_region,
                        ground=ground, actuator=actuator)
    finally:
        actuator.close()
        capturer.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="operation-grounding proof")
    parser.add_argument("instruction", help="例: その検索ボタン")
    parser.add_argument("--arm", action="store_true", help="実作動する(既定は dry-run)")
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/operate/test_proof.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/proof.py tests/operate/test_proof.py
git commit -m "feat(operate): add proof CLI to run grounding standalone

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: integration テスト（実サービス通し・rig のみ）

**Files:**
- Create: `tests/operate/test_integration.py`

**Interfaces:**
- Consumes: `build_config`、`MssCapturer`、`ground_target`（実 Holo2）。

- [ ] **Step 1: テストを書く（`@pytest.mark.integration`）**

`tests/operate/test_integration.py`:

```python
import urllib.request

import pytest

pytestmark = pytest.mark.integration


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/v1/models", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


async def test_grounding_returns_coords_in_region_real_holo2():
    pytest.importorskip("PIL")
    pytest.importorskip("mss")
    import aiohttp

    from kotoha.config import build_config
    from kotoha.operate.grounding import ground_target
    from kotoha.screen.capture import MssCapturer

    config = build_config()
    g_url = config.grounding_url or config.vlm_perception_url or config.ollama_url
    if not _reachable(g_url):
        pytest.skip("grounding endpoint not reachable")
    cap = MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture_with_region()
    if not cap:
        pytest.skip("screen capture unavailable")
    image_b64, region = cap
    async with aiohttp.ClientSession() as session:
        result = await ground_target(
            image_b64, instruction="画面の中央あたりの何か", region=region,
            model=config.grounding_model, base_url=g_url, api=config.grounding_api,
            session=session, timeout_s=60.0,
        )
    if result is None:
        pytest.skip("grounding returned no coordinates (model/prompt mismatch)")
    assert region.left <= result.x <= region.left + region.width
    assert region.top <= result.y <= region.top + region.height
```

- [ ] **Step 2: 既定実行で除外されることを確認**

Run: `pytest tests/operate/test_integration.py -m "not integration" -q`
Expected: 1 deselected

- [ ] **Step 3: 実サービス環境で通す（rig・手動）**

Run（Holo2 稼働時）: `pytest tests/operate/test_integration.py -m integration -v`
Expected: PASS（サービス不在なら skip）

- [ ] **Step 4: コミット**

```bash
git add tests/operate/test_integration.py
git commit -m "test(operate): add integration test for real Holo2 grounding

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 実機確認（integration・proof 環境）

ユニットでは担保しない実機部分。rig（4080＋VII、Holo2 配信後）で確認する。

- `python -m kotoha.operate.proof "その検索ボタン"` が前面アプリ・region・座標・dry-run 表示で正常終了し、`[raw]` から Holo2 の座標出力形式（0〜1000 正規化）を裏取りできる。`--arm` で実クリックする。
- `python -m kotoha.diagnostics` が `operation_enabled=True` のとき `[operate] grounding: OK, foreground: OK, dry-run/ARMED, allowlist=...` を示す。
- `pytest -m integration` が、実 Holo2 で capture→grounding→region 内座標を通す（無ければ skip）。
- `local_app` を操作有効・arm・allowlist 設定で起動し、「その検索ボタン押して」で実クリック、「送信して」で確認握手、kill キーで中断、を目視確認する。

## Self-Review（記入済み）

- **Spec coverage:** Config/配線→Task 1、OperationStats→Task 2、grounding（パース・写像・client）→Task 3、意図パース→Task 4、ポリシー→Task 5、actuator（dry-run/FAILSAFE/kill）→Task 6、Operator（経路A/B・確認後 allowlist 再評価・pending 失効）→Task 7、capture_with_region→Task 8、orchestrator 注入→Task 9、local_app/diagnostics/persona→Task 10、proof CLI→Task 11、integration→Task 12。spec の安全多層（enabled/dry-run/allowlist/confirm/kill/FAILSAFE/max-1）は Task 1・6・7 に分散して全て実装。網羅を確認。
- **Placeholder scan:** プレースホルダなし。各コード手順に実コードを記載。
- **Type consistency:** `ActionRequest(kind,target,text,keys,amount)`・`Region(left,top,width,height)`・`GroundResult(x,y,raw)`・`Operator(ground,capture_region,actuator,policy_cfg,get_foreground,stats,confirm_destructive,pending_ttl_s,clock)`・`Actuator(dry_run,kill_hotkey,max_actions,backend)`・`ground_target(...,session=None,...)`・`OperationStats.record/record_failure/record_ground_ms` はタスク間で一致。`policy_cfg` は `Config` を渡し、`operation_app_allowlist`/`operation_destructive_keywords`/`operation_destructive_hotkeys_always`/`hotkey_map` を読む点も一致。
