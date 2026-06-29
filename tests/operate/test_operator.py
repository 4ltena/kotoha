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


async def _ground_ok(image_b64, *, instruction, region):
    return GroundResult(x=100, y=200, raw="click(100,200)")


async def _ground_none(image_b64, *, instruction, region):
    return None


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
    out = await _op(act, ground=_ground_none).handle(
        "その検索ボタンをクリックして", user_id=0)
    assert act.executed == [] and out.startswith("[操作失敗]")
