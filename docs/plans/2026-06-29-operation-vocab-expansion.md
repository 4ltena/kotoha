# デスクトップ操作 語彙拡張 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 操作グラウンディングに drag・複数操作連鎖・grounding 自己整合チェックを足す。v1 の安全多層は不変、既定設定(max 1・self_check OFF)では v1 と挙動が変わらない。

**Architecture:** `actions.py` に drag 検出と引用保護 `parse_chain` を、`actuator.py` に drag dispatch を、`operator.py` に連鎖実行と自己整合 grounding を足す。単一操作(連鎖長 1)は v1 の出力形式を保ち、複数操作のときだけステップ集約形式にする。設計の正は [docs/specs/2026-06-29-operation-vocab-expansion-design.md](../specs/2026-06-29-operation-vocab-expansion-design.md)。

**Tech Stack:** Python 3.11+。新規依存なし(drag は既存 pyautogui)。

## Global Constraints

- Python `>=3.11`。手元 3.10 で検証。
- この環境は fake のみ。実作動・モデル DL・pyautogui/keyboard 実 import をしない。ユニットは fake backend / fake ground(async)で通す。
- v1 安全不変: 既定 OFF / dry-run 既定で drag・連鎖含む全 kind の実副作用抑止 / allowlist 空=全拒否 / 破壊確認 / global kill / FAILSAFE。連鎖は `operation_max_actions_per_command > 1` のときだけ有効(既定 1)。
- 後方互換: 単一操作(連鎖長 1)の戻り値・確認文・座標経路は v1 と同一。`actuator.execute(action, *, coords, coords_to=None)` は既存の coords 単独呼び出しを壊さない。
- best-effort: 例外を声ループへ上げない。
- コミットは Conventional Commits、英語タイトル、`Co-Authored-By: Claude <noreply@anthropic.com>`、author `4ltena`。

## ファイル構成

- 修正 `kotoha/config.py` / `.env.example` — `operation_grounding_self_check`/`operation_grounding_tolerance_px`、`operation_destructive_keywords` に `ゴミ箱`/`ごみ箱`。
- 修正 `kotoha/operate/actions.py` — `ActionRequest.to_target`、drag 検出、`parse_chain`(引用保護)。
- 修正 `kotoha/operate/policy.py` — `is_destructive` に `to_target`。
- 修正 `kotoha/operate/actuator.py` — `execute(..., coords_to=None)`、drag dispatch、backend.drag。
- 修正 `kotoha/operate/operator.py` — `parse_chain` 使用、`_run_chain`、連鎖破壊確認、`_ground_checked`。
- 追記テスト: 各 `tests/operate/test_*.py`、`tests/test_config.py`。

---

### Task 1: config の自己整合・破壊キーワード拡張

**Files:** Modify `kotoha/config.py`, `.env.example`; Test `tests/test_config.py`

**Interfaces:** Produces `Config.operation_grounding_self_check: bool = False`、`operation_grounding_tolerance_px: int = 30`、`operation_destructive_keywords` に `ゴミ箱`/`ごみ箱` 追加。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_config.py` に追記:

```python
def test_grounding_self_check_defaults():
    from kotoha.config import Config
    c = Config()
    assert c.operation_grounding_self_check is False
    assert c.operation_grounding_tolerance_px == 30
    assert "ゴミ箱" in c.operation_destructive_keywords
```

- [ ] **Step 2: 失敗を確認** — `pytest tests/test_config.py -k self_check -v` → FAIL（AttributeError）。

- [ ] **Step 3: 実装** — `kotoha/config.py` の `operation_destructive_keywords` タプルに `"ゴミ箱", "ごみ箱",` を追加。`operation_pending_ttl_s` の行付近(操作ブロック内)へ追記:

```python
    operation_grounding_self_check: bool = False   # True で同一対象を2回grounding し座標不一致なら棄却
    operation_grounding_tolerance_px: int = 30      # 自己整合の許容差(Chebyshev)
```

`.env.example` の操作ブロックへ追記:

```bash
# OPERATION_GROUNDING_SELF_CHECK=true   # 曖昧な対象を棄却(grounding 2回)
```

(env 配線は不要。これらは Config 既定で十分。`OPERATION_GROUNDING_SELF_CHECK` を実際に効かせたい場合の env 取り込みは後続。本タスクは Config フィールドの追加に留める。)

- [ ] **Step 4: 成功を確認** — `pytest tests/test_config.py -v` → PASS。

- [ ] **Step 5: コミット**

```bash
git add kotoha/config.py .env.example tests/test_config.py
git commit -m "feat(operate): add grounding self-check config and trash destructive keywords

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: actions.py — drag と引用保護 parse_chain

**Files:** Modify `kotoha/operate/actions.py`; Test `tests/operate/test_actions.py`

**Interfaces:**
- Produces: `ActionRequest(..., to_target="")`、`parse_intent` が drag を返す、`parse_chain(text, *, config) -> list[ActionRequest]`。
- Consumes: 既存 `_extract_target`、`_QUOTED`。

- [ ] **Step 1: 失敗するテストを書く** — `tests/operate/test_actions.py` に追記:

```python
from kotoha.operate.actions import parse_chain


def test_drag_extracts_from_and_to():
    a = parse_intent("ファイルをゴミ箱にドラッグして", config=CFG)
    assert a.kind == "drag" and a.target == "ファイル" and a.to_target == "ゴミ箱"


def test_drag_requires_both_targets():
    # 「を…に」が揃わない曖昧な発話は drag にしない
    assert parse_intent("ドラッグして", config=CFG) is None


def test_chain_splits_on_connectors():
    actions = parse_chain("検索ボタンを押して、それから送信ボタンを押して", config=CFG)
    assert len(actions) == 2
    assert actions[0].target == "検索ボタン" and actions[1].target == "送信ボタン"


def test_chain_protects_quoted_comma():
    # 引用内の 、 で分割しない: 型入力 + 1操作 = 2節
    actions = parse_chain("「a、b」と入力して、検索ボタンを押して", config=CFG)
    assert len(actions) == 2
    assert actions[0].kind == "type" and actions[0].text == "a、b"
    assert actions[1].kind == "click"


def test_chain_single_clause():
    actions = parse_chain("検索ボタンを押して", config=CFG)
    assert len(actions) == 1 and actions[0].kind == "click"


def test_chain_empty_on_no_intent():
    assert parse_chain("今日はいい天気", config=CFG) == []
```

- [ ] **Step 2: 失敗を確認** — `pytest tests/operate/test_actions.py -k "drag or chain" -v` → FAIL。

- [ ] **Step 3: 実装** — `kotoha/operate/actions.py`:

`ActionRequest` に `to_target: str = ""` を追加(`keys` の後)。

`_DRAG_WORDS` と drag 抽出を追加(モジュール上部の定数群へ):

```python
_DRAG_WORDS = ("ドラッグ", "移動", "動かし")


def _extract_drag(s: str) -> "tuple[str, str] | None":
    """「AをBに|へ <drag語>」から (A, B) を抽出。揃わなければ None。"""
    for w in _DRAG_WORDS:
        if w not in s:
            continue
        before = s.split(w)[0]
        if "を" not in before:
            return None
        a_part, rest = before.split("を", 1)
        # rest 末尾の に|へ より前を B とする
        to = ""
        for p in ("に", "へ"):
            if p in rest:
                to = rest.rsplit(p, 1)[0]
                break
        a = _extract_target(a_part + "を")   # _extract_target は末尾助詞を落とす
        b = _extract_target(to + "に") if to else ""
        if a and b:
            return a, b
        return None
    return None
```

`parse_intent` の先頭(right_click 判定の前)に drag 検出を入れる:

```python
    drag = _extract_drag(s)
    if drag is not None:
        return ActionRequest("drag", target=drag[0], to_target=drag[1])
```

`parse_chain` を追加(ファイル末尾):

```python
_CONNECTORS = ("そして", "それから", "、")   # してから/てから は動詞活用と衝突するため除外


def parse_chain(text, *, config) -> "list[ActionRequest]":
    """発話を接続語で節に割って各節を parse_intent する。引用 「…」/『…』内の接続語は無視する。"""
    s = text.strip()
    # 引用範囲をプレースホルダへ退避してから分割する。
    spans = []

    def _mask(m):
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    masked = _QUOTED.sub(_mask, s)
    # 接続語で分割
    parts = [masked]
    for c in _CONNECTORS:
        parts = [p for seg in parts for p in seg.split(c)]

    def _restore(seg):
        for i, original in enumerate(spans):
            seg = seg.replace(f"\x00{i}\x00", original)
        return seg

    out = []
    for seg in parts:
        seg = _restore(seg).strip()
        if not seg:
            continue
        a = parse_intent(seg, config=config)
        if a is not None:
            out.append(a)
    if not out:
        # 接続語で何も取れない単一発話: 全体を1意図として解釈
        a = parse_intent(s, config=config)
        return [a] if a is not None else []
    return out
```

注。`_QUOTED` は既存(`re.compile(r"[「『](.+?)[」』]")`)。drag 検出は click/double より前に置くこと(precedence)。

- [ ] **Step 4: 成功を確認** — `pytest tests/operate/test_actions.py -v` → PASS（既存 actions テストも緑）。

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/actions.py tests/operate/test_actions.py
git commit -m "feat(operate): add drag intent and quote-safe chain parsing

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: policy.py — is_destructive に to_target

**Files:** Modify `kotoha/operate/policy.py`; Test `tests/operate/test_policy.py`

- [ ] **Step 1: 失敗するテストを書く** — `tests/operate/test_policy.py` に追記:

```python
def test_drag_to_trash_is_destructive():
    from kotoha.operate.actions import ActionRequest
    from kotoha.operate.policy import is_destructive
    a = ActionRequest("drag", target="ファイル", to_target="ゴミ箱")
    assert is_destructive(a, destructive_keywords=("ゴミ箱",), hotkeys_always=True) is True
```

- [ ] **Step 2: 失敗を確認** — `pytest tests/operate/test_policy.py -k trash -v` → FAIL（to_target 未反映で False）。

- [ ] **Step 3: 実装** — `kotoha/operate/policy.py` の `is_destructive` の hay 連結に `to_target` を追加:

```python
    hay = ((action.target or "") + " " + (action.text or "") + " " + (getattr(action, "to_target", "") or "")).lower()
```

- [ ] **Step 4: 成功を確認** — `pytest tests/operate/test_policy.py -v` → PASS。

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/policy.py tests/operate/test_policy.py
git commit -m "feat(operate): include drag destination in destructive check

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: actuator.py — drag dispatch と coords_to

**Files:** Modify `kotoha/operate/actuator.py`; Test `tests/operate/test_actuator.py`

**Interfaces:** Produces `execute(action, *, coords, coords_to=None)`、`_do` が drag を処理、backend `drag(x1,y1,x2,y2)`。

- [ ] **Step 1: 失敗するテストを書く** — `tests/operate/test_actuator.py` に追記:

```python
def test_drag_dispatches_both_points():
    from kotoha.operate.actions import ActionRequest
    from kotoha.operate.actuator import Actuator

    class _B:
        def __init__(self): self.calls = []
        def drag(self, x1, y1, x2, y2): self.calls.append((x1, y1, x2, y2))

    b = _B()
    act = Actuator(dry_run=False, kill_hotkey="ctrl+alt+q", max_actions=1, backend=b)
    assert act.execute(ActionRequest("drag"), coords=(10, 20), coords_to=(30, 40)) is True
    assert b.calls == [(10, 20, 30, 40)]


def test_drag_dry_run_does_not_touch_backend():
    from kotoha.operate.actions import ActionRequest
    from kotoha.operate.actuator import Actuator

    class _B:
        def __init__(self): self.calls = []
        def drag(self, *a): self.calls.append(a)

    b = _B()
    act = Actuator(dry_run=True, kill_hotkey="ctrl+alt+q", max_actions=1, backend=b)
    assert act.execute(ActionRequest("drag"), coords=(1, 2), coords_to=(3, 4)) is True
    assert b.calls == []
```

- [ ] **Step 2: 失敗を確認** — `pytest tests/operate/test_actuator.py -k drag -v` → FAIL（unexpected kwarg coords_to）。

- [ ] **Step 3: 実装** — `kotoha/operate/actuator.py`:

`execute` 署名を `def execute(self, action, *, coords, coords_to=None) -> bool:` にし、`return self._do(action, coords)` を `return self._do(action, coords, coords_to)` にする。

`_do` 署名を `def _do(self, action, coords, coords_to=None) -> bool:` にし、`elif k == "hotkey":` の後・`else:` の前に追加:

```python
        elif k == "drag":
            b.drag(coords[0], coords[1], coords_to[0], coords_to[1])
```

`_describe_action(action, coords)` に drag を追加(`return k` の前):

```python
    if k == "drag":
        return f"drag {coords}->{getattr(action, 'to_target', '')}"
```

(`_describe_action` は coords_to を受けないので、ログは to_target 名で十分。必要なら署名拡張は任意。)

`_PyAutoGuiBackend` に drag を追加:

```python
    def drag(self, x1, y1, x2, y2):
        self._pg.moveTo(x1, y1)
        self._pg.dragTo(x2, y2, duration=0.3)
```

- [ ] **Step 4: 成功を確認** — `pytest tests/operate/test_actuator.py -v` → PASS（既存 actuator テストも緑。coords_to 既定 None で旧呼び出し不変）。

- [ ] **Step 5: コミット**

```bash
git add kotoha/operate/actuator.py tests/operate/test_actuator.py
git commit -m "feat(operate): add drag actuation with two-point coordinates

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: operator.py — 連鎖・drag・自己整合 grounding

**Files:** Modify `kotoha/operate/operator.py`; Test `tests/operate/test_operator.py`

**Interfaces:**
- Consumes: `parse_chain`(Task 2)、`is_destructive`+`to_target`(Task 3)、`execute(..., coords_to)`(Task 4)、`Config.operation_grounding_self_check`/`operation_grounding_tolerance_px`(Task 1)。
- Produces: `Operator.handle` が連鎖を実行。単一操作は v1 形式、複数操作は集約形式。pending は連鎖(list)。

- [ ] **Step 1: 失敗するテストを書く** — `tests/operate/test_operator.py` に追記(既存の `_Actuator`/`_cap`/`_ground_ok`/`CFG` を流用。`_Actuator` には Task1-fix で `begin_command` 済み):

```python
async def test_two_step_chain_executes_both():
    cfg = Config(operation_app_allowlist=("chrome.exe",), operation_max_actions_per_command=2)
    act = _Actuator()
    op = Operator(ground=_ground_ok, capture_region=_cap, actuator=act, policy_cfg=cfg,
                  get_foreground=lambda: "chrome.exe")
    out = await op.handle("検索を押して、それから更新を押して", user_id=0)
    assert len(act.executed) == 2
    assert "ステップ1" in out and "ステップ2" in out


async def test_chain_truncates_on_step_failure():
    cfg = Config(operation_app_allowlist=("chrome.exe",), operation_max_actions_per_command=3)
    act = _Actuator()
    calls = {"n": 0}

    async def ground(image_b64, *, instruction, region):
        calls["n"] += 1
        return None if calls["n"] == 2 else GroundResult(x=1, y=2, raw="")

    op = Operator(ground=ground, capture_region=_cap, actuator=act, policy_cfg=cfg,
                  get_foreground=lambda: "chrome.exe")
    out = await op.handle("Aを押して、Bを押して、Cを押して", user_id=0)
    assert len(act.executed) == 1            # 2手目の grounding 失敗で打ち切り
    assert "中止" in out or "2/3" in out


async def test_chain_destructive_confirmed_once():
    cfg = Config(operation_app_allowlist=("chrome.exe",), operation_max_actions_per_command=2)
    act = _Actuator()
    op = Operator(ground=_ground_ok, capture_region=_cap, actuator=act, policy_cfg=cfg,
                  get_foreground=lambda: "chrome.exe")
    first = await op.handle("検索を押して、それから送信を押して", user_id=0)
    assert act.executed == [] and "確認" in first   # 連鎖全体を1回確認
    await op.handle("うん", user_id=0)
    assert len(act.executed) == 2


async def test_single_action_keeps_v1_format():
    cfg = Config(operation_app_allowlist=("chrome.exe",))
    act = _Actuator()
    op = Operator(ground=_ground_ok, capture_region=_cap, actuator=act, policy_cfg=cfg,
                  get_foreground=lambda: "chrome.exe")
    out = await op.handle("その検索ボタンをクリックして", user_id=0)
    assert "ステップ" not in out and "操作した" in out   # v1 形式(集約しない)


async def test_drag_grounds_both_points():
    cfg = Config(operation_app_allowlist=("chrome.exe",))
    act = _Actuator()
    seen = []

    async def ground(image_b64, *, instruction, region):
        seen.append(instruction)
        return GroundResult(x=len(seen), y=len(seen), raw="")

    op = Operator(ground=ground, capture_region=_cap, actuator=act, policy_cfg=cfg,
                  get_foreground=lambda: "chrome.exe")
    await op.handle("ファイルをフォルダにドラッグして", user_id=0)
    assert seen == ["ファイル", "フォルダ"]
    assert act.executed and act.executed[0][0] == "drag"


async def test_self_check_rejects_inconsistent_grounding():
    cfg = Config(operation_app_allowlist=("chrome.exe",),
                 operation_grounding_self_check=True, operation_grounding_tolerance_px=10)
    act = _Actuator()
    seq = [GroundResult(x=100, y=100, raw=""), GroundResult(x=200, y=100, raw="")]

    async def ground(image_b64, *, instruction, region):
        return seq.pop(0)

    op = Operator(ground=ground, capture_region=_cap, actuator=act, policy_cfg=cfg,
                  get_foreground=lambda: "chrome.exe")
    out = await op.handle("ボタンをクリックして", user_id=0)
    assert act.executed == [] and out.startswith("[操作失敗]")   # 不一致で棄却
```

注。`_Actuator` フェイクの `execute` を `def execute(self, action, *, coords, coords_to=None): self.executed.append((action.kind, coords)); return True` に更新する(coords_to 受理)。`GroundResult` は `from kotoha.operate.grounding import GroundResult`。

- [ ] **Step 2: 失敗を確認** — `pytest tests/operate/test_operator.py -k "chain or drag or self_check or v1_format" -v` → FAIL。

- [ ] **Step 3: 実装** — `kotoha/operate/operator.py` を次へ置き換える(import と中核):

import を更新:

```python
from kotoha.operate.actions import is_affirmative, is_negative, parse_chain
from kotoha.operate.policy import app_allowed, is_destructive
```

`_NEEDS_GROUND` は不変。drag 用に補助を足し、`_confirm_prompt` の隣に集約・確認補助を追加:

```python
_NEEDS_GROUND = ("click", "double_click", "right_click")


def _confirm_prompt(action) -> str:
    what = action.target or {"type": "入力", "hotkey": action.keys}.get(action.kind, "操作")
    return f"{what}の操作を求めている。実行前に確認する"


def _confirm_prompt_chain(actions) -> str:
    labels = "、".join(a.target or a.text or a.keys or a.kind for a in actions)
    return f"{labels} の連鎖を求めている。実行前に確認する"


def _result_text(action, *, dry_run) -> str:
    label = action.target or action.text or action.keys or action.kind
    if dry_run:
        return f"（dry-run: {label} を操作するところ。実際にはしていない）"
    return f"（{label} を操作した）"


def _aggregate(results, done, total, *, truncated) -> str:
    body = " / ".join(results)
    return f"{body} ({done}/{total}で中止)" if truncated else body
```

`Operator._handle` を置き換える:

```python
    async def _handle(self, text, user_id):
        pend = self._pending.get(user_id)
        if pend is not None and self._clock() - pend[2] > self._ttl:
            del self._pending[user_id]
            self._rec("expired")
            pend = None
        if pend is not None:
            if is_negative(text):
                del self._pending[user_id]
                self._rec("refused")
                return "操作を取りやめた"
            if is_affirmative(text):
                actions, ptext, _ = pend
                del self._pending[user_id]
                if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
                    return "対象アプリが変わったため取りやめた"
                return await self._execute_actions(actions, ptext)
            del self._pending[user_id]   # 中立応答: 破棄して新意図へ

        actions = parse_chain(text, config=self._cfg)
        if not actions:
            return None
        self._rec("intents")
        if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
            return self._fail("allowlist", "許可外アプリ")
        if self._confirm and any(self._destructive(a) for a in actions):
            self._pending[user_id] = (actions, text, self._clock())
            self._rec("confirmed_pending")
            return _confirm_prompt(actions[0]) if len(actions) == 1 else _confirm_prompt_chain(actions)
        return await self._execute_actions(actions, text)
```

`Operator` に補助とチェーン実行を追加(`_run` を置き換え):

```python
    def _destructive(self, action) -> bool:
        return is_destructive(
            action,
            destructive_keywords=self._cfg.operation_destructive_keywords,
            hotkeys_always=self._cfg.operation_destructive_hotkeys_always,
        )

    def _safe_capture(self):
        try:
            return self._capture_region()
        except Exception:
            return None

    async def _ground_checked(self, image_b64, instruction, region):
        """grounding して実OS座標を返す。self_check 時は2回一致を要求し、不一致は None。"""
        t0 = self._clock()
        r1 = await self._ground(image_b64, instruction=instruction, region=region)
        if self._stats is not None:
            self._stats.record_ground_ms((self._clock() - t0) * 1000)
        if r1 is None:
            return None
        if not getattr(self._cfg, "operation_grounding_self_check", False):
            self._rec("grounded")
            return (r1.x, r1.y)
        r2 = await self._ground(image_b64, instruction=instruction, region=region)
        if r2 is None:
            return None
        tol = self._cfg.operation_grounding_tolerance_px
        if max(abs(r1.x - r2.x), abs(r1.y - r2.y)) > tol:
            return None
        self._rec("grounded")
        return (r1.x, r1.y)

    async def _run_one(self, action, instruction, image_b64, region):
        """1ステップ。(ok, 文) を返す。grounding 失敗・kill・execute 失敗は (False, 失敗文)。"""
        coords = None
        coords_to = None
        if action.kind in _NEEDS_GROUND:
            coords = await self._ground_checked(image_b64, action.target or instruction or action.kind, region)
            if coords is None:
                return False, self._fail("ground", "対象が見つからない")
        elif action.kind == "drag":
            coords = await self._ground_checked(image_b64, action.target or instruction or action.kind, region)
            if coords is None:
                return False, self._fail("ground", "対象が見つからない")
            coords_to = await self._ground_checked(image_b64, action.to_target or action.kind, region)
            if coords_to is None:
                return False, self._fail("ground", "対象が見つからない")
        ok = self._actuator.execute(action, coords=coords, coords_to=coords_to)
        if self._actuator.aborted():
            self._rec("aborted")
            return False, _FAIL + "中止(kill)"
        if not ok:
            return False, self._fail("execute", "実行できなかった")
        self._rec("executed")
        return True, _result_text(action, dry_run=self._actuator.is_dry_run())

    async def _execute_actions(self, actions, instruction):
        if len(actions) == 1:
            return await self._run(actions[0], instruction)
        return await self._run_chain(actions, instruction)

    async def _run(self, action, instruction):
        self._actuator.begin_command()
        cap = self._safe_capture()
        if not cap:
            return self._fail("capture", "キャプチャ失敗")
        image_b64, region = cap
        _ok, text = await self._run_one(action, instruction, image_b64, region)
        return text

    async def _run_chain(self, actions, instruction):
        self._actuator.begin_command()
        results = []
        for i, action in enumerate(actions, 1):
            cap = self._safe_capture()
            if not cap:
                results.append(f"ステップ{i}: " + self._fail("capture", "キャプチャ失敗"))
                return _aggregate(results, i, len(actions), truncated=True)
            image_b64, region = cap
            if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
                results.append(f"ステップ{i}: " + self._fail("allowlist", "許可外アプリ"))
                return _aggregate(results, i, len(actions), truncated=True)
            ok, text = await self._run_one(action, instruction, image_b64, region)
            results.append(f"ステップ{i}: " + text)
            if not ok:
                return _aggregate(results, i, len(actions), truncated=True)
        return _aggregate(results, len(actions), len(actions), truncated=False)
```

注。旧 `_run(self, action, instruction)` は上の新 `_run` に置き換わる(単一操作の v1 形式を保つ)。`_NEEDS_GROUND` に drag は含めない(drag は専用分岐で2点 grounding)。

- [ ] **Step 4: 成功を確認** — `pytest tests/operate/test_operator.py -v` → PASS（既存 operator テストも緑。単一操作は v1 形式のままなので `[操作失敗]` で始まる失敗・`操作した` 成功の既存アサートが通る）。

- [ ] **Step 5: 全体テスト** — `pytest -m "not integration" -q` → 回帰なしで全 PASS。

- [ ] **Step 6: コミット**

```bash
git add kotoha/operate/operator.py tests/operate/test_operator.py
git commit -m "feat(operate): chain execution, drag grounding, and grounding self-check

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review（記入済み）

- **Spec coverage:** config(self_check/trash)→Task 1、drag+parse_chain→Task 2、is_destructive to_target→Task 3、actuator drag/coords_to→Task 4、連鎖実行+自己整合+drag dual-ground+連鎖確認→Task 5。網羅を確認。
- **Placeholder scan:** なし。各手順に実コード。
- **Type consistency:** `ActionRequest.to_target`、`parse_chain(text,*,config)->list`、`execute(action,*,coords,coords_to=None)`、`_run`/`_run_chain`/`_run_one`/`_ground_checked`、pending=(actions,text,ts) はタスク間で一致。単一操作の v1 形式維持(後方互換)も一致。
