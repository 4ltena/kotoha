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
        self._pending = {}   # user_id -> (ActionRequest, text, ts)

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
                action, ptext, _ = pend
                del self._pending[user_id]
                if not app_allowed(self._get_foreground(), allowlist=self._cfg.operation_app_allowlist):
                    return "対象アプリが変わったため取りやめた"
                return await self._run(action, ptext)
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
            self._pending[user_id] = (action, text, self._clock())
            self._rec("confirmed_pending")
            return _confirm_prompt(action)
        return await self._run(action, text)

    async def _run(self, action, instruction):
        self._actuator.begin_command()
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
            inst = action.target or instruction or action.kind
            t0 = self._clock()
            result = await self._ground(image_b64, instruction=inst, region=region)
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
