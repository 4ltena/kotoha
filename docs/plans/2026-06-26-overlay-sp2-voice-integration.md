# Overlay SP2 — Voice-Loop Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python 側に、Kotoha の状態(idle/listening/thinking/speaking)と口パク振幅をオーバーレイへ配信する仕組み(WebSocket ブリッジ + 疎結合イベントフック)を追加する。

**Architecture:** `Orchestrator` と `LocalSpeaker` は「events シンク」(`state(value)` / `mouth(level)`)を任意で受け取り、状態遷移と再生振幅をそこへ通知する。既定は no-op の `NullEvents` で**挙動不変**。`OverlayBridge`(aiohttp WebSocket サーバ)が events シンクを実装し、接続したオーバーレイ(SP1)へ JSON を配信する。`local_app` が設定有効時にブリッジを起動・注入する。

**Tech Stack:** Python 3.10+(当面)、asyncio、aiohttp(既存依存・WS サーバに再利用)、numpy、pytest / pytest-asyncio。

## Global Constraints

- **オーバーレイ無効時は挙動完全不変**: `events` 既定は `NullEvents`(no-op)、`LocalSpeaker.on_amplitude` 既定は `None`。既存ユニットテストは無改変で緑のまま。
- **新規 Python ランタイム依存を増やさない**: WS サーバは既存の `aiohttp` を使う。
- **localhost 限定**: 既定 `host="127.0.0.1"`, `port=8770`。
- **プロトコル(JSON, server→client)**: `{"type": "state", "value": "idle|listening|thinking|speaking"}` / `{"type": "mouth", "value": <0.0–1.0>}`。
- **音声内部表現**: 16kHz / mono / float32 [-1.0, 1.0](フェーズ1から不変)。
- **テスト方針**: ユニットは音声ハード・実ネットワーク不要(fake 注入)。実 WS 往復は `@pytest.mark.integration`。既定実行は `-m "not integration"`。
- **コミット**: author/committer はユーザーの git 設定。タイトル(1行目)は英語。末尾に空行をはさんで `Co-Authored-By: Claude <noreply@anthropic.com>`。

---

## File Structure

- `kotoha/events.py`(新規) — events シンクの no-op 実装 `NullEvents`(I/F: `state(value: str)`, `mouth(level: float)`)。純粋・依存なし。
- `kotoha/overlay_bridge.py`(新規) — `OverlayBridge`(events シンク I/F を実装した aiohttp WebSocket サーバ)。
- `kotoha/orchestrator.py`(変更) — `events` 受け口 + 状態遷移の発信。
- `kotoha/voice/speaker.py`(変更) — `on_amplitude` で再生チャンクの RMS を通知。
- `kotoha/config.py`(変更) — `overlay_enabled` / `overlay_ws_host` / `overlay_ws_port`。
- `kotoha/local_app.py`(変更) — 設定有効時にブリッジ起動 + `events`/`on_amplitude` 注入。
- テスト: `tests/test_events.py`、`tests/test_overlay_bridge.py`、`tests/test_orchestrator.py`(追記)、`tests/voice/test_speaker.py`(追記)、`tests/test_config_local.py`(追記)、`tests/test_local_app.py`(追記)。

> **本プランの非対象**: 発話オンセットでの `listening`(`VadSegmenter` への onset フック)は spec §4.1 で最優先度が低い任意項目。本プランでは `listening` は **barge-in 反応のみ**実装し、受け入れ基準(spec §10)を満たす。オンセット版は将来の小タスク。

---

### Task 1: events シンク no-op (`NullEvents`)

**Files:**
- Create: `kotoha/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Produces: `class NullEvents` — `state(self, value: str) -> None`、`mouth(self, level: float) -> None`(いずれも何もしない)。events シンクのダックタイプ I/F の基準実装。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_events.py`:
```python
from kotoha.events import NullEvents


def test_null_events_state_and_mouth_are_noops():
    ev = NullEvents()
    assert ev.state("speaking") is None
    assert ev.mouth(0.5) is None
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_events.py -q`
Expected: FAIL(`ModuleNotFoundError: No module named 'kotoha.events'`)

- [ ] **Step 3: 最小実装**

`kotoha/events.py`:
```python
"""オーバーレイ等への状態通知 events シンクの no-op 実装。

events シンクのダックタイプ I/F:
    state(value: str) -> None   # "idle" | "listening" | "thinking" | "speaking"
    mouth(level: float) -> None # 0.0–1.0 の口開度

NullEvents は何もしない既定実装。OverlayBridge(SP2)が同 I/F を実装する。
"""


class NullEvents:
    """何もしない events シンク(既定)。"""

    def state(self, value: str) -> None:
        return None

    def mouth(self, level: float) -> None:
        return None
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_events.py -q`
Expected: PASS(1 passed)

- [ ] **Step 5: commit**

```bash
git add kotoha/events.py tests/test_events.py
git commit -m "feat: add NullEvents no-op sink for overlay state notifications

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Orchestrator に状態イベント発信を追加

**Files:**
- Modify: `kotoha/orchestrator.py`
- Test: `tests/test_orchestrator.py`(追記)

**Interfaces:**
- Consumes: `kotoha.events.NullEvents`(Task 1)。
- Produces: `Orchestrator.__init__(..., events=NullEvents())`。状態遷移で `self._events.state(...)` を発信:
  - `"thinking"`: `handle_utterance` で STT 成功・履歴追加後、ターン開始時。
  - `"speaking"`: そのターンで最初に実音声を再生する直前(1回のみ)。`_audio_to_playback` か `_speak_fallback` の先着。
  - `"idle"`: `_run_turn` の finally(ターン終了)。
  - `"listening"`: `request_bargein`(ユーザー割り込み)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_orchestrator.py` の末尾に追記(既存の `_FakeTranscriber` / `_make_llm` / `_fake_tts` / `_RecPlayer` / `_FakeVad` を再利用):
```python
class _RecEvents:
    def __init__(self):
        self.states = []

    def state(self, value):
        self.states.append(value)

    def mouth(self, level):
        pass


async def test_events_emitted_for_normal_turn():
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["はい。"]),
        tts=_fake_tts,
        player=_RecPlayer(),
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        events=_RecEvents() if False else _RecEvents(),
    )
    ev = orch._events
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert ev.states == ["thinking", "speaking", "idle"]


async def test_events_empty_transcript_emits_nothing():
    ev = _RecEvents()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("   "),
        llm_stream=_make_llm(["x。"]),
        tts=_fake_tts,
        player=_RecPlayer(),
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        events=ev,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert ev.states == []


async def test_events_speaking_emitted_on_tts_fallback():
    async def _bad_tts(text):
        if text == "ダメ。":
            raise RuntimeError("tts down")
        return ("WAV:" + text).encode()

    ev = _RecEvents()
    orch = Orchestrator(
        transcriber=_FakeTranscriber("やあ"),
        llm_stream=_make_llm(["ダメ。"]),
        tts=_bad_tts,
        player=_RecPlayer(),
        model="m",
        vad_factory=lambda: _FakeVad(),
        persona=persona,
        fallback_text="ごめん。",
        events=ev,
    )
    await orch.handle_utterance(1, np.zeros(16000, dtype=np.float32))
    assert ev.states == ["thinking", "speaking", "idle"]
```

> 1つ目のテストの `events=_RecEvents() if False else _RecEvents()` は単に `events=_RecEvents()` と等価(`orch._events` で記録器を取り出す)。

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: FAIL(`TypeError: __init__() got an unexpected keyword argument 'events'`)

- [ ] **Step 3: 最小実装**

`kotoha/orchestrator.py` を次のとおり変更する。

(3-1) import 追加。既存:
```python
from kotoha.llm.sentence_splitter import SentenceSplitter
```
の直後に追加:
```python
from kotoha.events import NullEvents
```

(3-2) `__init__` シグネチャに `events` を追加。既存:
```python
        splitter_factory=SentenceSplitter,
        loop=None,
    ):
```
を次に置換:
```python
        splitter_factory=SentenceSplitter,
        loop=None,
        events=NullEvents(),
    ):
```

(3-3) `__init__` 本体に状態を保存。既存:
```python
        self._assistant_buf = ""
```
の直後に追加:
```python
        self._events = events
        self._spoke = False   # このターンで "speaking" を発信済みか
```

(3-4) `handle_utterance` で thinking を発信。既存:
```python
        self.history.append({"role": "user", "content": text})
        messages = self.persona.build_messages(list(self.history))
```
を次に置換:
```python
        self.history.append({"role": "user", "content": text})
        self._events.state("thinking")
        messages = self.persona.build_messages(list(self.history))
```

(3-5) `_run_turn` 開始で speaking フラグをリセット。既存:
```python
        splitter = self.splitter_factory()
        self._assistant_buf = ""
```
を次に置換:
```python
        splitter = self.splitter_factory()
        self._assistant_buf = ""
        self._spoke = False
```

(3-6) `_run_turn` の finally で idle を発信。既存:
```python
        finally:
            self._save_partial()
            self._sentence_q = None
            self._play_q = None
```
を次に置換:
```python
        finally:
            self._save_partial()
            self._sentence_q = None
            self._play_q = None
            self._events.state("idle")
```

(3-7) speaking を1回だけ出すヘルパを追加。`_speak_fallback` メソッド定義の直前に追加:
```python
    def _emit_speaking_once(self) -> None:
        if not self._spoke:
            self._spoke = True
            self._events.state("speaking")

```

(3-8) `_audio_to_playback` で実音声再生直前に speaking。既存:
```python
    async def _audio_to_playback(self) -> None:
        while True:
            wav = await self._play_q.get()
            if wav is _SENTINEL:
                return
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )
```
を次に置換:
```python
    async def _audio_to_playback(self) -> None:
        while True:
            wav = await self._play_q.get()
            if wav is _SENTINEL:
                return
            self._emit_speaking_once()
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )
```

(3-9) `_speak_fallback` で再生直前に speaking。既存:
```python
    async def _speak_fallback(self) -> None:
        try:
            wav = await asyncio.wait_for(
                self.tts(self.fallback_text), timeout=self._tts_timeout
            )
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )
```
を次に置換:
```python
    async def _speak_fallback(self) -> None:
        try:
            wav = await asyncio.wait_for(
                self.tts(self.fallback_text), timeout=self._tts_timeout
            )
            self._emit_speaking_once()
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )
```

(3-10) `request_bargein` で listening を発信。既存:
```python
    def request_bargein(self, user_id: Optional[int] = None) -> None:
        # 中断時点までの bot 発話を保存 (§4) -> (c)キューフラッシュ -> (b)LLM中断 -> (a)再生停止
        self._save_partial()
```
を次に置換:
```python
    def request_bargein(self, user_id: Optional[int] = None) -> None:
        # 中断時点までの bot 発話を保存 (§4) -> (c)キューフラッシュ -> (b)LLM中断 -> (a)再生停止
        self._events.state("listening")
        self._save_partial()
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: PASS(新規3件 + 既存4件)

回帰確認(既定 NullEvents で既存挙動不変):
Run: `python -m pytest tests/test_bargein.py tests/test_orchestrator.py -q`
Expected: PASS(全件)

- [ ] **Step 5: commit**

```bash
git add kotoha/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: emit lifecycle state events from Orchestrator (default no-op)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: LocalSpeaker に振幅(口パク)コールバックを追加

**Files:**
- Modify: `kotoha/voice/speaker.py`
- Test: `tests/voice/test_speaker.py`(追記)

**Interfaces:**
- Produces: `LocalSpeaker(*, sd=None, loop=None, on_amplitude=None)`。`on_amplitude: Callable[[float], None] | None`。再生コールバックで各チャンクの RMS(0.0–1.0 にクランプ)を `on_amplitude(level)` で通知。コールバックは音声スレッドで動くため、呼び出し先がスレッド安全であること(Task 5 の `OverlayBridge.mouth` が担保)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/voice/test_speaker.py` の末尾に追記(既存の `_make_wav` / `FakeSd` を再利用):
```python
async def test_on_amplitude_reports_levels_for_nonsilent_audio():
    rate = 32000
    i16 = (np.ones(1024) * 16384).astype(np.int16)   # 一定振幅 0.5
    wav = _make_wav(i16, rate=rate, channels=1)

    levels = []
    fake = FakeSd(auto_finish=True)
    spk = LocalSpeaker(sd=fake, on_amplitude=lambda v: levels.append(v))
    await spk.play_and_wait(wav)

    assert levels                              # 振幅が通知された
    assert all(0.0 <= v <= 1.0 for v in levels)
    assert max(levels) > 0.0                    # 無音ではない


async def test_on_amplitude_zero_for_silence():
    wav = _make_wav(np.zeros(1024, dtype=np.int16), rate=32000, channels=1)
    levels = []
    fake = FakeSd(auto_finish=True)
    spk = LocalSpeaker(sd=fake, on_amplitude=lambda v: levels.append(v))
    await spk.play_and_wait(wav)

    assert levels
    assert max(levels) == 0.0
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/voice/test_speaker.py -q -m "not integration"`
Expected: FAIL(`TypeError: __init__() got an unexpected keyword argument 'on_amplitude'`)

- [ ] **Step 3: 最小実装**

`kotoha/voice/speaker.py` を変更する。

(3-1) `__init__` を変更。既存:
```python
    def __init__(self, *, sd=None, loop=None):
        if sd is None:
            import sounddevice as sd  # 実機でのみ遅延 import(テストは fake を注入)
        self._sd = sd
        self._loop = loop
        self._interrupted = False
        self._stream = None
```
を次に置換:
```python
    def __init__(self, *, sd=None, loop=None, on_amplitude=None):
        if sd is None:
            import sounddevice as sd  # 実機でのみ遅延 import(テストは fake を注入)
        self._sd = sd
        self._loop = loop
        self._on_amplitude = on_amplitude
        self._interrupted = False
        self._stream = None
```

(3-2) 再生 callback で RMS を通知。既存:
```python
        def callback(outdata, frames, time_info, status):
            nonlocal idx
            if self._interrupted:
                raise self._sd.CallbackStop
            chunk = data[idx : idx + frames]
            n = len(chunk)
            outdata[:n] = chunk
            idx += n
            if n < frames:
                outdata[n:] = 0.0  # 最終(部分)バッファを 0 埋め
                raise self._sd.CallbackStop
```
を次に置換:
```python
        def callback(outdata, frames, time_info, status):
            nonlocal idx
            if self._interrupted:
                raise self._sd.CallbackStop
            chunk = data[idx : idx + frames]
            n = len(chunk)
            outdata[:n] = chunk
            idx += n
            if self._on_amplitude is not None and n > 0:
                level = float(np.sqrt(np.mean(np.square(chunk[:n]))))
                try:
                    self._on_amplitude(min(1.0, level))
                except Exception:
                    pass  # 口パク通知は best-effort(再生を妨げない)
            if n < frames:
                outdata[n:] = 0.0  # 最終(部分)バッファを 0 埋め
                raise self._sd.CallbackStop
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/voice/test_speaker.py -q -m "not integration"`
Expected: PASS(新規2件 + 既存3件)

- [ ] **Step 5: commit**

```bash
git add kotoha/voice/speaker.py tests/voice/test_speaker.py
git commit -m "feat: report per-chunk RMS amplitude from LocalSpeaker for lip-sync

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Config にオーバーレイ設定を追加

**Files:**
- Modify: `kotoha/config.py`
- Test: `tests/test_config_local.py`(追記)

**Interfaces:**
- Produces: `Config` に `overlay_enabled: bool = False`、`overlay_ws_host: str = "127.0.0.1"`、`overlay_ws_port: int = 8770` を追加(frozen 維持・末尾追記)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_config_local.py` の末尾に追記:
```python
def test_overlay_defaults():
    cfg = Config()
    assert cfg.overlay_enabled is False
    assert cfg.overlay_ws_host == "127.0.0.1"
    assert cfg.overlay_ws_port == 8770
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_config_local.py -q`
Expected: FAIL(`AttributeError: 'Config' object has no attribute 'overlay_enabled'`)

- [ ] **Step 3: 最小実装**

`kotoha/config.py` の `Config` 末尾フィールド(`mic_blocksize` の行)の直後に追加:
```python
    # --- デスクトップ・オーバーレイ (SP2) ---
    overlay_enabled: bool = False
    overlay_ws_host: str = "127.0.0.1"
    overlay_ws_port: int = 8770
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_config_local.py -q`
Expected: PASS(新規1件 + 既存4件)

- [ ] **Step 5: commit**

```bash
git add kotoha/config.py tests/test_config_local.py
git commit -m "feat: add overlay settings to Config (disabled by default)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: OverlayBridge(aiohttp WebSocket サーバ + events シンク)

**Files:**
- Create: `kotoha/overlay_bridge.py`
- Test: `tests/test_overlay_bridge.py`

**Interfaces:**
- Consumes: `aiohttp`(`aiohttp.web`)。
- Produces: `class OverlayBridge(*, host="127.0.0.1", port=8770, loop=None)`:
  - `state(self, value: str) -> None` / `mouth(self, level: float) -> None`(events シンク I/F。任意スレッドから安全。loop 未設定なら no-op)。
  - `async _broadcast(self, message: dict) -> None`(接続クライアントへ JSON 配信。失敗クライアントは除去。クライアント 0 なら no-op)。
  - `async start(self) -> None` / `async stop(self) -> None`(WS サーバ起動/停止。`GET /ws`)。
  - 属性 `_clients: set`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_overlay_bridge.py`:
```python
from kotoha.overlay_bridge import OverlayBridge


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_str(self, s):
        self.sent.append(s)


class _BadWS:
    async def send_str(self, s):
        raise RuntimeError("closed")


async def test_broadcast_sends_json_to_clients():
    b = OverlayBridge()
    ws = _FakeWS()
    b._clients.add(ws)
    await b._broadcast({"type": "state", "value": "speaking"})
    assert ws.sent == ['{"type": "state", "value": "speaking"}']


async def test_broadcast_no_clients_is_noop():
    b = OverlayBridge()
    await b._broadcast({"type": "mouth", "value": 0.5})   # 例外を出さない


async def test_broadcast_drops_failed_client():
    b = OverlayBridge()
    bad = _BadWS()
    b._clients.add(bad)
    await b._broadcast({"type": "state", "value": "idle"})
    assert bad not in b._clients


def test_state_and_mouth_without_loop_are_safe():
    b = OverlayBridge()           # loop 未設定
    b.state("idle")               # 例外を出さない(no-op)
    b.mouth(0.3)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_overlay_bridge.py -q`
Expected: FAIL(`ModuleNotFoundError: No module named 'kotoha.overlay_bridge'`)

- [ ] **Step 3: 最小実装**

`kotoha/overlay_bridge.py`:
```python
"""オーバーレイ(SP1)へ状態/口パクイベントを配信する WebSocket ブリッジ。

events シンク I/F(state/mouth)を実装し、接続中の各クライアントへ JSON を
ブロードキャストする。声ループを絶対にブロック・失敗させない(best-effort)。
state()/mouth() は任意スレッドから呼ばれうるため、loop.call_soon_threadsafe で
イベントループへマーシャリングする。
"""

import asyncio
import json
import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class OverlayBridge:
    def __init__(self, *, host: str = "127.0.0.1", port: int = 8770, loop=None):
        self._host = host
        self._port = port
        self._loop = loop
        self._clients: set = set()
        self._runner = None

    # ---- events シンク(任意スレッドから安全) ----
    def state(self, value: str) -> None:
        self._submit({"type": "state", "value": value})

    def mouth(self, level: float) -> None:
        self._submit({"type": "mouth", "value": float(level)})

    def _submit(self, message: dict) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._schedule, message)

    def _schedule(self, message: dict) -> None:
        asyncio.ensure_future(self._broadcast(message))

    # ---- 配信 ----
    async def _broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(message)
        for ws in list(self._clients):
            try:
                await ws.send_str(data)
            except Exception:
                self._clients.discard(ws)

    # ---- WS サーバ ----
    async def _handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for _ in ws:
                pass   # SP1/SP2 はサーバ→クライアントの一方向。受信は無視。
        finally:
            self._clients.discard(ws)
        return ws

    async def start(self) -> None:
        self._loop = self._loop or asyncio.get_running_loop()
        app = web.Application()
        app.router.add_get("/ws", self._handle_ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("OverlayBridge listening on ws://%s:%s/ws", self._host, self._port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_overlay_bridge.py -q`
Expected: PASS(4 passed)

- [ ] **Step 5(任意): 実 WS 往復の integration テストを書く**

`tests/test_overlay_bridge.py` の末尾に追記:
```python
import aiohttp
import pytest


@pytest.mark.integration
async def test_real_ws_roundtrip():
    bridge = OverlayBridge(port=8771)
    await bridge.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("http://127.0.0.1:8771/ws") as ws:
                # クライアント登録を待ってから配信
                import asyncio as _a
                await _a.sleep(0.05)
                await bridge._broadcast({"type": "state", "value": "thinking"})
                msg = await ws.receive(timeout=1.0)
                assert msg.data == '{"type": "state", "value": "thinking"}'
    finally:
        await bridge.stop()
```

Run: `python -m pytest tests/test_overlay_bridge.py -q`(integration は既定除外/skip)
Expected: PASS(4 passed, 1 deselected)

- [ ] **Step 6: commit**

```bash
git add kotoha/overlay_bridge.py tests/test_overlay_bridge.py
git commit -m "feat: add OverlayBridge WebSocket server and events sink

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: local_app でブリッジ起動 + 注入

**Files:**
- Modify: `kotoha/local_app.py`
- Test: `tests/test_local_app.py`(追記)

**Interfaces:**
- Consumes: `OverlayBridge`(Task 5)、`NullEvents`(Task 1)、`Orchestrator`/`LocalSpeaker`(既存)。
- Produces:
  - `build_orchestrator(config, *, session, loop, transcriber=None, player=None, vad_factory=SileroVad, events=NullEvents(), on_amplitude=None)`。`events` を `Orchestrator(...)` へ渡す。`player is None` のとき `LocalSpeaker(loop=loop, on_amplitude=on_amplitude)` を生成。
  - `run_local`: `config.overlay_enabled` のとき `OverlayBridge` を起動し `events=bridge` / `on_amplitude=bridge.mouth` を注入(無効時は従来どおり)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_local_app.py` の末尾に追記(既存の `_cfg` を再利用):
```python
def test_build_orchestrator_passes_events(monkeypatch):
    captured = {}

    class _FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(local_app, "Orchestrator", _FakeOrch)

    sentinel = object()
    local_app.build_orchestrator(
        _cfg(),
        session=object(),
        loop=object(),
        transcriber=object(),
        player=object(),
        events=sentinel,
    )
    assert captured["events"] is sentinel


def test_build_orchestrator_defaults_events_to_null(monkeypatch):
    from kotoha.events import NullEvents

    captured = {}

    class _FakeOrch:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(local_app, "Orchestrator", _FakeOrch)

    local_app.build_orchestrator(
        _cfg(),
        session=object(),
        loop=object(),
        transcriber=object(),
        player=object(),
    )
    assert isinstance(captured["events"], NullEvents)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/test_local_app.py -q`
Expected: FAIL(`TypeError: build_orchestrator() got an unexpected keyword argument 'events'`)

- [ ] **Step 3: 最小実装**

`kotoha/local_app.py` を変更する。

(3-1) import 追加。既存:
```python
from kotoha.health import check_local_services
```
の直後に追加:
```python
from kotoha.events import NullEvents
from kotoha.overlay_bridge import OverlayBridge
```

(3-2) `build_orchestrator` シグネチャ拡張。既存:
```python
def build_orchestrator(
    config,
    *,
    session,
    loop,
    transcriber=None,
    player=None,
    vad_factory=SileroVad,
):
```
を次に置換:
```python
def build_orchestrator(
    config,
    *,
    session,
    loop,
    transcriber=None,
    player=None,
    vad_factory=SileroVad,
    events=NullEvents(),
    on_amplitude=None,
):
```

(3-3) 既定 player に on_amplitude を渡す。既存:
```python
    if player is None:
        player = LocalSpeaker(loop=loop)
```
を次に置換:
```python
    if player is None:
        player = LocalSpeaker(loop=loop, on_amplitude=on_amplitude)
```

(3-4) `Orchestrator(...)` に events を渡す。既存:
```python
        tts_timeout=config.tts_timeout_s,
        play_timeout=config.play_timeout_s,
        loop=loop,
    )
```
を次に置換:
```python
        tts_timeout=config.tts_timeout_s,
        play_timeout=config.play_timeout_s,
        loop=loop,
        events=events,
    )
```

(3-5) `run_local` でブリッジ起動・注入。既存:
```python
        orch = build_orchestrator(config, session=session, loop=loop)
        mic = MicCapture(
```
を次に置換:
```python
        bridge = None
        events = NullEvents()
        on_amplitude = None
        if config.overlay_enabled:
            bridge = OverlayBridge(
                host=config.overlay_ws_host, port=config.overlay_ws_port, loop=loop
            )
            await bridge.start()
            events = bridge
            on_amplitude = bridge.mouth
            print(
                f"[overlay] WS サーバ起動: "
                f"ws://{config.overlay_ws_host}:{config.overlay_ws_port}/ws"
            )

        orch = build_orchestrator(
            config,
            session=session,
            loop=loop,
            events=events,
            on_amplitude=on_amplitude,
        )
        mic = MicCapture(
```

(3-6) 終了時にブリッジを停止。既存:
```python
        try:
            await asyncio.Event().wait()   # KeyboardInterrupt まで常駐
        finally:
            mic.stop()
```
を次に置換:
```python
        try:
            await asyncio.Event().wait()   # KeyboardInterrupt まで常駐
        finally:
            mic.stop()
            if bridge is not None:
                await bridge.stop()
```

- [ ] **Step 4: 緑を確認**

Run: `python -m pytest tests/test_local_app.py -q`
Expected: PASS(新規2件 + 既存1件)

全体回帰:
Run: `python -m pytest -q -m "not integration"`
Expected: PASS(全件・回帰なし)

- [ ] **Step 5: commit**

```bash
git add kotoha/local_app.py tests/test_local_app.py
git commit -m "feat: wire OverlayBridge into local_app when overlay enabled

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 完了確認(SP2 全体スモーク)

- [ ] `python -m pytest -q -m "not integration"` が全件 PASS(オーバーレイ無効時の既存挙動が不変)。
- [ ] (任意・実機)`Config(overlay_enabled=True)` で `python -m kotoha.local_app` を起動し、`ws://127.0.0.1:8770/ws` に簡易 WS クライアントで接続 → 発話に応じて `state`/`mouth` JSON が流れることを目視確認(SP1 完成後はオーバーレイで確認)。

## 受け入れ基準(spec §10 対応)

- 声ループ動作中、events シンク経由で `thinking`→`speaking`→`idle` と barge-in 時の `listening`、再生中の `mouth` 振幅が発信される。
- `overlay_enabled=False`(既定)では `NullEvents` + `on_amplitude=None` により**声ループの挙動・性能は従来どおり**(既存ユニットテスト緑)。
