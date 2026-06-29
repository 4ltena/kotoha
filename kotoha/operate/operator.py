"""操作の統合中核。会話前段プロバイダとして注入され、確認待ち状態をターン跨ぎで保持する。

handle が返す文字列を orchestrator が system メッセージへ注入する。操作意図が無ければ
None。best-effort で例外を声ループへ上げない。直列化されたターン処理内でのみ呼ばれる。
"""

import logging
import time

from kotoha.operate.actions import is_affirmative, is_negative, parse_chain, parse_intent
from kotoha.operate.policy import app_allowed, is_destructive

logger = logging.getLogger(__name__)

_FAIL = "[操作失敗] "
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
        self._pending = {}   # user_id -> (actions_list, text, ts)

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

        if self._cfg.operation_max_actions_per_command > 1:
            actions = parse_chain(text, config=self._cfg)
        else:
            a = parse_intent(text, config=self._cfg)
            actions = [a] if a is not None else []
        if not actions:
            return None
        self._rec("intents")
        if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
            return self._fail("allowlist", "許可外アプリ")
        destructive = any(self._destructive(a) for a in actions) or self._text_has_destructive(text)
        if self._confirm and destructive:
            self._pending[user_id] = (actions, text, self._clock())
            self._rec("confirmed_pending")
            return _confirm_prompt(actions[0]) if len(actions) == 1 else _confirm_prompt_chain(actions)
        return await self._execute_actions(actions, text)

    def _destructive(self, action) -> bool:
        return is_destructive(
            action,
            destructive_keywords=self._cfg.operation_destructive_keywords,
            hotkeys_always=self._cfg.operation_destructive_hotkeys_always,
        )

    def _text_has_destructive(self, text) -> bool:
        hay = (text or "").lower()
        return any(kw.lower() in hay for kw in self._cfg.operation_destructive_keywords)

    def _safe_capture(self):
        try:
            return self._capture_region()
        except Exception:
            return None

    async def _ground_checked(self, image_b64, instruction, region):
        """grounding して (座標, reason) を返す。reason は "" / "notfound" / "ambiguous"。
        self_check 時は2回一致を要求し、不一致は "ambiguous"。latency は全呼び出しを通算。"""
        t0 = self._clock()
        r1 = await self._ground(image_b64, instruction=instruction, region=region)
        if r1 is None:
            if self._stats is not None:
                self._stats.record_ground_ms((self._clock() - t0) * 1000)
            return None, "notfound"
        if not getattr(self._cfg, "operation_grounding_self_check", False):
            if self._stats is not None:
                self._stats.record_ground_ms((self._clock() - t0) * 1000)
            self._rec("grounded")
            return (r1.x, r1.y), ""
        r2 = await self._ground(image_b64, instruction=instruction, region=region)
        if self._stats is not None:
            self._stats.record_ground_ms((self._clock() - t0) * 1000)
        if r2 is None:
            return None, "notfound"
        tol = self._cfg.operation_grounding_tolerance_px
        if max(abs(r1.x - r2.x), abs(r1.y - r2.y)) > tol:
            return None, "ambiguous"
        self._rec("grounded")
        return (r1.x, r1.y), ""

    async def _run_one(self, action, instruction, image_b64, region):
        """1ステップ。(ok, 文) を返す。grounding 失敗・kill・execute 失敗は (False, 失敗文)。"""
        coords = None
        coords_to = None
        if action.kind in _NEEDS_GROUND:
            coords, reason = await self._ground_checked(image_b64, action.target or instruction or action.kind, region)
            if coords is None:
                msg = "対象が曖昧" if reason == "ambiguous" else "対象が見つからない"
                return False, self._fail("ground", msg)
        elif action.kind == "drag":
            coords, reason = await self._ground_checked(image_b64, action.target or instruction or action.kind, region)
            if coords is None:
                msg = "対象が曖昧" if reason == "ambiguous" else "対象が見つからない"
                return False, self._fail("ground", msg)
            coords_to, reason_to = await self._ground_checked(image_b64, action.to_target or action.kind, region)
            if coords_to is None:
                msg = "対象が曖昧" if reason_to == "ambiguous" else "対象が見つからない"
                return False, self._fail("ground", msg)
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
