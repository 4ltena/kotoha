# 画面知覚 Phase 2 実装計画 — 統合と proof の土台

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 の画面知覚ループに、計測(`PerceptionStats`)・目視確認(proof CLI)・自動検証(integration テスト)・観測の配線(終了サマリと診断拡張)を載せ、知覚を「測れて・通せて・見える」状態にする。

**Architecture:** 観測専用の純粋オブジェクト `PerceptionStats` を中核に、`ScreenPerceiver` がそれを更新し、proof CLI・`local_app`・診断がその snapshot を読む疎結合構成。実機依存は proof CLI と integration テストに閉じ込め、ユニットは fake 注入で通す。新しい知覚能力は足さない。

**Tech Stack:** Python 3.11+, asyncio, aiohttp, 既存の `kotoha/screen/`(state/detector/capture/perceiver/sanitize)と `kotoha/llm/vlm_client.py`、`kotoha/health.py`。

設計の正は [docs/specs/2026-06-29-screen-perception-phase2-design.md](../specs/2026-06-29-screen-perception-phase2-design.md)。Phase 1 の正は [docs/specs/2026-06-28-screen-perception-design.md](../specs/2026-06-28-screen-perception-design.md)。

## Global Constraints

- Python は `>=3.11`。ユニット検証は手元の 3.10 スクラッチ venv で行う(`str | None` 等は 3.10 ランタイムで評価可能)。
- 知覚は best-effort。計測・proof・診断・integration のいずれも会話ループを止めない。`PerceptionStats` の記録メソッドは例外を投げない。
- 画面知覚は既定 OFF のオプトイン(`screen_perception_enabled: bool = False`)。
- スクリーンショットはディスクへ保存しない。要約テキストのみ保持する。
- 重い依存(mss/dxcam/PIL)は関数・メソッド内で遅延 import する。
- ユニットテストは GPU・外部サービス・画面ハードなしで通す(fake 注入)。実機要は `@pytest.mark.integration` ＋ テスト内 `pytest.importorskip` と軽い疎通。既定実行は `pytest -m "not integration"`。
- コミットは Conventional Commits。タイトルは英語。本文末尾に空行＋`Co-Authored-By: Claude <noreply@anthropic.com>`。author は既定の git 設定(`4ltena`)を使う。

## ファイル構成

- 新規 `kotoha/screen/stats.py` — `PerceptionStats`(観測専用)。
- 修正 `kotoha/screen/perceiver.py` — `ScreenPerceiver.__init__` に `stats=None`、`tick`/`run` に計測フック。
- 新規 `kotoha/screen/proof.py` — proof CLI(`python -m kotoha.screen.proof`)。テスト可能な `run_proof` と実機結線の `main`。
- 修正 `kotoha/local_app.py` — `PerceptionStats` を生成して perceiver へ渡し、終了時に1行サマリ。
- 修正 `kotoha/diagnostics.py` — 画面知覚レディネス `diagnose_screen` を追加し、`build_config` 起動に揃える。
- 新規 `tests/screen/test_stats.py`、`tests/screen/test_proof.py`、`tests/screen/test_integration.py`、各既存テストへ追記。

---

### Task 1: PerceptionStats（観測専用オブジェクト）

**Files:**
- Create: `kotoha/screen/stats.py`
- Test: `tests/screen/test_stats.py`

**Interfaces:**
- Produces: `PerceptionStats()`。メソッド `record_capture(ms: float)`, `record_describe(ms: float)`, `record_skip()`, `record_summary_update()`, `record_failure(kind: str)`（kind は `"capture"` | `"vlm"`）, `set_mode(mode: str)`, `snapshot() -> dict`, `summary_line() -> str`。snapshot のキー: captures, describes, skips, summary_updates, failures(dict), last_capture_ms, avg_capture_ms, last_vlm_ms, avg_vlm_ms, mode。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_stats.py`:

```python
from kotoha.screen.stats import PerceptionStats


def test_counts_and_failures():
    s = PerceptionStats()
    s.record_capture(100.0)
    s.record_capture(200.0)
    s.record_describe(5000.0)
    s.record_skip()
    s.record_skip()
    s.record_summary_update()
    s.record_failure("vlm")
    snap = s.snapshot()
    assert snap["captures"] == 2
    assert snap["describes"] == 1
    assert snap["skips"] == 2
    assert snap["summary_updates"] == 1
    assert snap["failures"] == {"capture": 0, "vlm": 1}


def test_averages_and_last():
    s = PerceptionStats()
    s.record_capture(100.0)
    s.record_capture(300.0)
    s.record_describe(4000.0)
    s.record_describe(8000.0)
    snap = s.snapshot()
    assert snap["last_capture_ms"] == 300.0
    assert snap["avg_capture_ms"] == 200.0
    assert snap["last_vlm_ms"] == 8000.0
    assert snap["avg_vlm_ms"] == 6000.0


def test_averages_zero_when_empty():
    snap = PerceptionStats().snapshot()
    assert snap["avg_capture_ms"] == 0.0
    assert snap["avg_vlm_ms"] == 0.0
    assert snap["mode"] == "normal"


def test_summary_line_is_human_readable():
    s = PerceptionStats()
    s.record_describe(6000.0)
    s.set_mode("game_powersave")
    line = s.summary_line()
    assert "describes=1" in line
    assert "vlm_avg=6.0s" in line
    assert "mode=game_powersave" in line
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_stats.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.screen.stats`）

- [ ] **Step 3: 実装する**

`kotoha/screen/stats.py`:

```python
"""画面知覚ループの計数とレイテンシをスレッドセーフに保持する観測専用オブジェクト。

perceiver(書き手・ワーカーとループの両スレッド)と CLI・local_app・診断(読み手)を
疎結合にする。会話にも知覚判断にも影響しない。記録メソッドは例外を投げない。
"""

import threading


class PerceptionStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._captures = 0
        self._describes = 0
        self._skips = 0
        self._summary_updates = 0
        self._failures = {"capture": 0, "vlm": 0}
        self._cap_ms_sum = 0.0
        self._cap_ms_last = 0.0
        self._vlm_ms_sum = 0.0
        self._vlm_ms_last = 0.0
        self._mode = "normal"

    def record_capture(self, ms: float) -> None:
        with self._lock:
            self._captures += 1
            self._cap_ms_last = ms
            self._cap_ms_sum += ms

    def record_describe(self, ms: float) -> None:
        with self._lock:
            self._describes += 1
            self._vlm_ms_last = ms
            self._vlm_ms_sum += ms

    def record_skip(self) -> None:
        with self._lock:
            self._skips += 1

    def record_summary_update(self) -> None:
        with self._lock:
            self._summary_updates += 1

    def record_failure(self, kind: str) -> None:
        with self._lock:
            self._failures[kind] = self._failures.get(kind, 0) + 1

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode

    def snapshot(self) -> dict:
        with self._lock:
            cap_avg = self._cap_ms_sum / self._captures if self._captures else 0.0
            vlm_avg = self._vlm_ms_sum / self._describes if self._describes else 0.0
            return {
                "captures": self._captures,
                "describes": self._describes,
                "skips": self._skips,
                "summary_updates": self._summary_updates,
                "failures": dict(self._failures),
                "last_capture_ms": self._cap_ms_last,
                "avg_capture_ms": cap_avg,
                "last_vlm_ms": self._vlm_ms_last,
                "avg_vlm_ms": vlm_avg,
                "mode": self._mode,
            }

    def summary_line(self) -> str:
        s = self.snapshot()
        fails = sum(s["failures"].values())
        return (
            f"captures={s['captures']} describes={s['describes']} "
            f"skips={s['skips']} vlm_avg={s['avg_vlm_ms'] / 1000:.1f}s "
            f"fail={fails} mode={s['mode']}"
        )
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_stats.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/stats.py tests/screen/test_stats.py
git commit -m "feat(screen): add PerceptionStats for perception-loop observability

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: ScreenPerceiver への計測フック

**Files:**
- Modify: `kotoha/screen/perceiver.py`
- Test: `tests/screen/test_perceiver.py`

**Interfaces:**
- Consumes: `PerceptionStats`(Task 1)。
- Produces: `ScreenPerceiver(..., stats=None)`。`tick` が capture/describe の所要時間を計り、skip・failure・summary_update・mode を `stats` へ記録する。`stats=None` のときは無記録で既存挙動と一致。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_perceiver.py` に追記。

```python
class _RecStats:
    def __init__(self):
        self.events = []

    def record_capture(self, ms): self.events.append(("capture", ms))
    def record_describe(self, ms): self.events.append(("describe", ms))
    def record_skip(self): self.events.append(("skip",))
    def record_summary_update(self): self.events.append(("summary",))
    def record_failure(self, kind): self.events.append(("fail", kind))
    def set_mode(self, m): self.events.append(("mode", m))


async def test_stats_recorded_on_successful_describe():
    ctx = _ctx()
    st = _RecStats()
    p = ScreenPerceiver(
        capturer=_Capturer(), describe=_describe_factory("画面。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5, stats=st,
    )
    assert await p.tick() is True
    kinds = [e[0] for e in st.events]
    assert "capture" in kinds and "describe" in kinds and "summary" in kinds


async def test_stats_skip_on_identical_frame():
    ctx = _ctx()
    st = _RecStats()
    p = ScreenPerceiver(
        capturer=_Capturer(value="SAME"), describe=_describe_factory("画面。"),
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5, stats=st,
    )
    await p.tick()
    await p.tick()
    kinds = [e[0] for e in st.events]
    assert kinds.count("describe") == 1   # 2回目は VLM を呼ばない
    assert "skip" in kinds


async def test_stats_failure_on_describe_error():
    ctx = _ctx()
    st = _RecStats()

    async def boom(image_b64):
        raise RuntimeError("vlm down")

    p = ScreenPerceiver(
        capturer=_Capturer(), describe=boom,
        screen_ctx=ctx, normal_interval_s=4.0, realtime_interval_s=0.5, stats=st,
    )
    assert await p.tick() is False
    assert ("fail", "vlm") in st.events
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_perceiver.py -k stats -v`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'stats'`）

- [ ] **Step 3: 実装する**

`kotoha/screen/perceiver.py` の `__init__` 末尾(`self._last_capture_b64 = None` の後)に追記。

```python
        self._stats = stats
```

`__init__` 署名へ `sleep=asyncio.sleep,` の後に追加。

```python
        sleep=asyncio.sleep,
        stats=None,
    ):
```

`tick` を次に置き換える。

```python
    async def tick(self) -> bool:
        """1サイクル。要約を更新できたら True。"""
        mode = self._screen_ctx.mode
        if self._stats is not None:
            self._stats.set_mode(mode)
        if mode == "game_powersave":
            return False
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            image_b64 = await loop.run_in_executor(self._executor, self._capturer.capture)
        except Exception:
            logger.warning("screen capture raised", exc_info=True)
            if self._stats is not None:
                self._stats.record_failure("capture")
            return False
        if not image_b64:
            return False
        if self._stats is not None:
            self._stats.record_capture((loop.time() - t0) * 1000)
        if image_b64 == self._last_capture_b64:
            # 画面が変わっていない: 重い VLM を呼ばず、要約の鮮度だけ更新する。
            self._screen_ctx.touch()
            if self._stats is not None:
                self._stats.record_skip()
            return False
        t1 = loop.time()
        try:
            summary = await self._describe(image_b64)
        except Exception:
            logger.warning("VLM describe failed", exc_info=True)
            if self._stats is not None:
                self._stats.record_failure("vlm")
            return False
        if self._stats is not None:
            self._stats.record_describe((loop.time() - t1) * 1000)
        summary = normalize_summary(summary)   # 装飾除去・最大2文へ均す
        if summary:
            self._last_capture_b64 = image_b64
            self._screen_ctx.set_summary(summary)
            if self._stats is not None:
                self._stats.record_summary_update()
            return True
        return False
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_perceiver.py -v`
Expected: PASS（既存の perceiver テスト含め緑。`stats=None` の既存テストは無記録で不変）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/perceiver.py tests/screen/test_perceiver.py
git commit -m "feat(screen): record capture/describe/skip latency into PerceptionStats

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: proof CLI（`python -m kotoha.screen.proof`）

**Files:**
- Create: `kotoha/screen/proof.py`
- Test: `tests/screen/test_proof.py`

**Interfaces:**
- Consumes: `build_config`(`kotoha/config.py`)、`ScreenPerceiver`(Task 2)、`PerceptionStats`(Task 1)、`vlm_describe`、`MssCapturer`/`DxcamCapturer`、`get_foreground_info`/`is_game_active`/`resolve_mode`。
- Produces: `async run_proof(*, perceiver, screen_ctx, stats, cycles, out=print) -> None`(テスト可能な中核)。`main(argv=None) -> int`(実機結線。`python -m kotoha.screen.proof`)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/screen/test_proof.py`:

```python
from kotoha.screen.proof import run_proof
from kotoha.screen.stats import PerceptionStats
from kotoha.screen.state import ScreenContext
from kotoha.screen.perceiver import ScreenPerceiver


class _Cap:
    def capture(self):
        return "IMG"


async def test_run_proof_prints_summary_and_stats_each_cycle():
    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    stats = PerceptionStats()

    async def describe(image_b64):
        return "画面にエディタ。"

    p = ScreenPerceiver(
        capturer=_Cap(), describe=describe, screen_ctx=ctx,
        normal_interval_s=4.0, realtime_interval_s=0.5, stats=stats,
    )
    lines = []
    await run_proof(perceiver=p, screen_ctx=ctx, stats=stats, cycles=2, out=lines.append)
    text = "\n".join(lines)
    assert "画面にエディタ" in text       # 要約を表示
    assert "captures=" in text           # stats を表示
    assert "[1/2]" in text and "[2/2]" in text
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/screen/test_proof.py -v`
Expected: FAIL（`ModuleNotFoundError: kotoha.screen.proof`）

- [ ] **Step 3: 実装する**

`kotoha/screen/proof.py`:

```python
"""画面知覚だけを単体起動して目視確認する proof CLI。

GPT-SoVITS とマイクには触れない。build_config() で .env を反映し、実キャプチャと
実 VLM で知覚ループを回して要約と PerceptionStats を表示する。`python -m kotoha.screen.proof`。
"""

import argparse
import asyncio
import functools

import aiohttp

from kotoha.config import build_config
from kotoha.llm.vlm_client import vlm_describe
from kotoha.screen.capture import DxcamCapturer, MssCapturer
from kotoha.screen.detector import get_foreground_info, is_game_active, resolve_mode
from kotoha.screen.perceiver import ScreenPerceiver
from kotoha.screen.state import ScreenContext
from kotoha.screen.stats import PerceptionStats


async def run_proof(*, perceiver, screen_ctx, stats, cycles, out=print) -> None:
    """知覚ループを cycles 回まわし、各サイクルの要約と stats を表示する(実機/テスト共用)。"""
    for i in range(cycles):
        updated = await perceiver.tick()
        out(f"[{i + 1}/{cycles}] updated={updated} summary={screen_ctx.get_summary()!r}")
        out("  " + stats.summary_line())


def _build_describe(config, session):
    return functools.partial(
        vlm_describe,
        model=config.vlm_perception_model,
        base_url=config.vlm_perception_url or config.ollama_url,
        prompt=config.vlm_perception_prompt,
        api=config.vlm_perception_api,
        session=session,
        timeout_s=config.vlm_perception_timeout_s,
    )


async def _main(args) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    config = build_config()
    backend = args.backend or config.screen_capture_backend
    if backend == "dxcam":
        capturer = DxcamCapturer(max_long_edge=config.screen_capture_max_long_edge)
    else:
        capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)

    fg = get_foreground_info()
    active = is_game_active(
        fg, detect_fullscreen=config.screen_game_detect_fullscreen,
        process_names=config.screen_game_process_names,
    )
    print(f"[foreground] {fg} -> {resolve_mode(active, config.screen_game_mode)}")
    print(f"[vlm] model={config.vlm_perception_model} "
          f"url={config.vlm_perception_url or config.ollama_url} api={config.vlm_perception_api}")

    stats = PerceptionStats()
    screen_ctx = ScreenContext(summary_max_age_s=config.screen_summary_max_age_s)
    timeout = aiohttp.ClientTimeout(total=None, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        perceiver = ScreenPerceiver(
            capturer=capturer, describe=_build_describe(config, session),
            screen_ctx=screen_ctx,
            normal_interval_s=config.screen_normal_interval_s,
            realtime_interval_s=config.screen_game_realtime_interval_s,
            poll_s=config.screen_game_poll_s, stats=stats,
        )
        if args.duration:
            deadline = asyncio.get_running_loop().time() + args.duration
            while asyncio.get_running_loop().time() < deadline:
                await run_proof(perceiver=perceiver, screen_ctx=screen_ctx,
                                stats=stats, cycles=1)
                await asyncio.sleep(config.screen_normal_interval_s)
        else:
            await run_proof(perceiver=perceiver, screen_ctx=screen_ctx,
                            stats=stats, cycles=args.cycles)
        try:
            perceiver._executor.shutdown(wait=False)
        except Exception:
            pass
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="screen-perception proof")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--duration", type=float, default=0.0, help="秒。指定時は時間優先")
    parser.add_argument("--backend", choices=["mss", "dxcam"], default=None)
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    import sys

    sys.exit(main())
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `pytest tests/screen/test_proof.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: コミット**

```bash
git add kotoha/screen/proof.py tests/screen/test_proof.py
git commit -m "feat(screen): add proof CLI to run perception standalone

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: integration テスト（実サービス通し）

**Files:**
- Create: `tests/screen/test_integration.py`

**Interfaces:**
- Consumes: `build_config`、`MssCapturer`、`vlm_describe`、`normalize_summary`、`ScreenContext`、`Orchestrator`、`persona`(Task 1〜2 と Phase 1 の成果)。

- [ ] **Step 1: テストを書く（`@pytest.mark.integration`）**

`tests/screen/test_integration.py`:

```python
import urllib.request

import pytest

pytestmark = pytest.mark.integration


def _ollama_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


async def test_capture_describe_returns_summary_real_vlm():
    pytest.importorskip("PIL")
    pytest.importorskip("mss")
    import aiohttp

    from kotoha.config import build_config
    from kotoha.llm.vlm_client import vlm_describe
    from kotoha.screen.capture import MssCapturer
    from kotoha.screen.sanitize import normalize_summary

    config = build_config()
    if not _ollama_reachable(config.ollama_url):
        pytest.skip("Ollama not reachable")
    img = MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture()
    if not img:
        pytest.skip("screen capture unavailable")
    async with aiohttp.ClientSession() as session:
        summary = await vlm_describe(
            img, model=config.vlm_perception_model,
            base_url=config.vlm_perception_url or config.ollama_url,
            prompt=config.vlm_perception_prompt, api=config.vlm_perception_api,
            session=session, timeout_s=60.0,
        )
    assert normalize_summary(summary)   # 実 VLM が非空の要約を返す


async def test_perception_to_orchestrator_injection_end_to_end():
    pytest.importorskip("PIL")
    pytest.importorskip("mss")
    import aiohttp
    import numpy as np

    from kotoha.config import build_config
    from kotoha.llm import persona
    from kotoha.llm.vlm_client import vlm_describe
    from kotoha.orchestrator import Orchestrator
    from kotoha.screen.capture import MssCapturer
    from kotoha.screen.sanitize import normalize_summary
    from kotoha.screen.state import ScreenContext

    config = build_config()
    if not _ollama_reachable(config.ollama_url):
        pytest.skip("Ollama not reachable")
    img = MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture()
    if not img:
        pytest.skip("screen capture unavailable")
    async with aiohttp.ClientSession() as session:
        summary = await vlm_describe(
            img, model=config.vlm_perception_model,
            base_url=config.vlm_perception_url or config.ollama_url,
            prompt=config.vlm_perception_prompt, api=config.vlm_perception_api,
            session=session, timeout_s=60.0,
        )
    ctx = ScreenContext()
    ctx.set_summary(normalize_summary(summary))

    captured = []

    def llm(messages, *, model):
        captured.append([dict(m) for m in messages])

        async def gen():
            yield "はい。"

        return gen()

    async def tts(text):
        return b""

    class _Tr:
        def transcribe(self, audio):
            return "いまどう?"

    class _Player:
        def is_playing(self):
            return False

        def stop(self):
            pass

        async def play_and_wait(self, wav):
            return True

    orch = Orchestrator(
        transcriber=_Tr(), llm_stream=llm, tts=tts, player=_Player(),
        model="m", vad_factory=lambda: object(), persona=persona, screen_context=ctx,
    )
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    contents = [m["content"] for m in captured[0] if m["role"] == "system"]
    assert any(c.startswith("【画面の様子】") for c in contents)
    assert any(ctx.get_summary() in c for c in contents)   # 実要約が注入される
```

- [ ] **Step 2: 既定実行で除外されることを確認**

Run: `pytest tests/screen/test_integration.py -m "not integration" -q`
Expected: 2 deselected（既定では走らない）

- [ ] **Step 3: 実サービス環境で通すことを確認**

Run（Ollama + vision モデル稼働時）: `pytest tests/screen/test_integration.py -m integration -v`
Expected: PASS（サービス不在なら skip）

- [ ] **Step 4: コミット**

```bash
git add tests/screen/test_integration.py
git commit -m "test(screen): add integration tests for capture-VLM-injection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 観測の配線（local_app）と診断拡張（diagnostics）

**Files:**
- Modify: `kotoha/local_app.py`
- Modify: `kotoha/diagnostics.py`
- Test: `tests/test_local_app.py`, `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `PerceptionStats`(Task 1)、`probe_llm_endpoint`(`kotoha/health.py`)。
- Produces: `local_app` が知覚有効時に `PerceptionStats` を生成し perceiver へ渡し、終了時に `[screen] stats: ...` を表示する。`diagnostics.diagnose_screen(config, *, session, capture_probe=None) -> dict | None` が画面知覚レディネス(VLM 到達 + 1枚キャプチャ)を返す(無効時 None)。

- [ ] **Step 1: 診断の失敗するテストを書く**

`tests/test_diagnostics.py` に追記(無ければ新規)。

```python
from kotoha.config import Config
from kotoha.diagnostics import diagnose_screen


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


async def test_diagnose_screen_none_when_disabled():
    cfg = Config(screen_perception_enabled=False)
    assert await diagnose_screen(cfg, session=_OkSession()) is None


async def test_diagnose_screen_reports_vlm_and_capture():
    cfg = Config(
        screen_perception_enabled=True,
        ollama_url="http://localhost:11434",
        vlm_perception_api="ollama",
    )
    result = await diagnose_screen(
        cfg, session=_OkSession(), capture_probe=lambda: "IMGB64",
    )
    assert result["vlm_ok"] is True
    assert result["capture_ok"] is True


async def test_diagnose_screen_capture_failure_is_caught():
    cfg = Config(screen_perception_enabled=True, vlm_perception_api="ollama")

    def boom():
        raise RuntimeError("no display")

    result = await diagnose_screen(cfg, session=_OkSession(), capture_probe=boom)
    assert result["capture_ok"] is False
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `pytest tests/test_diagnostics.py -k diagnose_screen -v`
Expected: FAIL（`ImportError: cannot import name 'diagnose_screen'`）

- [ ] **Step 3: diagnostics を実装する**

`kotoha/diagnostics.py` の import に追記。

```python
from kotoha.config import Config, build_config
from kotoha.health import check_local_services, probe_llm_endpoint
```

`diagnose`(関数定義)の後に追記。

```python
async def diagnose_screen(config, *, session, capture_probe=None) -> dict | None:
    """画面知覚レディネスを返す。無効なら None。VLM 到達と1枚キャプチャ可否を見る。"""
    if not getattr(config, "screen_perception_enabled", False):
        return None
    vlm_url = config.vlm_perception_url or config.ollama_url
    vlm_ok = await probe_llm_endpoint(session, vlm_url, api=config.vlm_perception_api)
    if capture_probe is None:
        def capture_probe():
            from kotoha.screen.capture import MssCapturer
            return MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture()
    try:
        capture_ok = bool(capture_probe())
    except Exception:
        capture_ok = False
    return {"vlm_url": vlm_url, "vlm_ok": vlm_ok, "capture_ok": capture_ok}
```

`run_diagnostics` の `print(format_report(result))` の直後に追記。

```python
        screen = await diagnose_screen(config, session=session)
    if screen is not None:
        print(f"[screen]    vlm({screen['vlm_url']}): {'OK' if screen['vlm_ok'] else 'DOWN'}, "
              f"capture: {'OK' if screen['capture_ok'] else 'FAIL'}")
```

注意。`diagnose_screen` は `async with ... session` の中で呼ぶ必要があるため、`run_diagnostics` の `result = await diagnose(config, session=session)` の直後・同じ `async with` ブロック内に `screen = await diagnose_screen(config, session=session)` を置き、`print` はブロックの外で行う。下記の置換で全体を一致させる。

`run_diagnostics` の本体を次へ置き換える。

```python
async def run_diagnostics(config: Config) -> int:
    """疎通診断を実行してレポートを表示し、終了コードを返す(0=準備OK)。"""
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        result = await diagnose(config, session=session)
        screen = await diagnose_screen(config, session=session)
    print(format_report(result))
    if screen is not None:
        print(f"[screen]    vlm({screen['vlm_url']}): {'OK' if screen['vlm_ok'] else 'DOWN'}, "
              f"capture: {'OK' if screen['capture_ok'] else 'FAIL'}")

    print("\n[audio devices]")
    try:
        print(list_audio_devices())
    except Exception as e:
        print(f"unavailable: {e} ([local] extra / sounddevice may be missing)")

    ok = result["ollama"] and result["gptsovits"] and result["model_present"]
    print("\n=> ready" if ok else "\n=> some items are not satisfied (see above)")
    return 0 if ok else 1
```

`main` を `build_config` 起動へ揃える。

```python
def main() -> None:
    import sys

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(run_diagnostics(build_config())))
```

- [ ] **Step 4: 診断テストを実行して成功を確認**

Run: `pytest tests/test_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: local_app の失敗するテストを書く**

`tests/test_local_app.py` に追記。

```python
def test_perception_stats_summary_line_is_printable():
    # 終了時サマリに使う PerceptionStats.summary_line が文字列を返すことの最小確認。
    from kotoha.screen.stats import PerceptionStats

    line = PerceptionStats().summary_line()
    assert isinstance(line, str) and "captures=" in line
```

- [ ] **Step 6: local_app に stats 配線を実装する**

`kotoha/local_app.py` の import に追記。

```python
from kotoha.screen.stats import PerceptionStats
```

`run_local` の画面知覚ブロック、`screen_ctx = ScreenContext(...)` の直後に `screen_stats` を作る。

```python
        screen_stats = None
        if config.screen_perception_enabled:
            screen_ctx = ScreenContext(summary_max_age_s=config.screen_summary_max_age_s)
            screen_stats = PerceptionStats()
```

`ScreenPerceiver(...)` 呼び出しへ `stats=screen_stats` を追加する。

```python
            perceiver = ScreenPerceiver(
                capturer=capturer, describe=describe, screen_ctx=screen_ctx,
                normal_interval_s=config.screen_normal_interval_s,
                realtime_interval_s=config.screen_game_realtime_interval_s,
                poll_s=config.screen_game_poll_s, stats=screen_stats,
            )
```

`finally` の `await asyncio.gather(*screen_tasks, return_exceptions=True)` の直後に追記する。

```python
            if screen_stats is not None:
                print("[screen] stats: " + screen_stats.summary_line())
```

注意。`screen_stats` は `if config.screen_perception_enabled:` ブロックの外側(`screen_ctx = None` / `screen_tasks = []` と同じ階層)で `None` 初期化してから、ブロック内で代入する。`finally` から参照するため。

- [ ] **Step 7: 全体テストを実行**

Run: `pytest -m "not integration" -q`
Expected: 既存＋新規がすべて PASS（回帰なし）

- [ ] **Step 8: コミット**

```bash
git add kotoha/local_app.py kotoha/diagnostics.py tests/test_local_app.py tests/test_diagnostics.py
git commit -m "feat(screen): wire PerceptionStats summary and screen diagnostics

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 実機確認（integration・proof 環境）

ユニットでは担保しない実機部分。4080 単騎(VII 未接続)で確認する。

- `python -m kotoha.screen.proof --cycles 3` が、前面窓・VLM 設定・各サイクルの要約と stats を表示して正常終了する。
- `python -m kotoha.diagnostics` が、`screen_perception_enabled=True`(`.env` で設定)のとき `[screen] vlm: OK, capture: OK` を示す。
- `pytest -m integration` が、実 Ollama の vision モデルがある環境で capture → 要約 → 注入を通す(無ければ skip)。
- `local_app` を画面知覚有効で起動・終了し、`[screen] stats:` に妥当な実測(captures>0、vlm_avg が実機レイテンシ)が出る。

## Self-Review（記入済み）

- **Spec coverage:** PerceptionStats→Task 1、計測フック→Task 2、proof CLI→Task 3、integration テスト→Task 4、終了サマリ＋診断拡張→Task 5。スコープ外(操作グラウンディング・VII 分離新規・要約刷新)は plan にも含めない。網羅を確認。
- **Placeholder scan:** プレースホルダなし。各コード手順に実コードを記載。
- **Type consistency:** `record_capture/describe/skip/summary_update/failure`・`set_mode`・`snapshot`・`summary_line`、`stats=None`、`run_proof(*, perceiver, screen_ctx, stats, cycles, out)`、`diagnose_screen(config, *, session, capture_probe)` の名前と引数はタスク間で一致。`probe_llm_endpoint` は Phase 2 で既に `kotoha/health.py` に存在する。
