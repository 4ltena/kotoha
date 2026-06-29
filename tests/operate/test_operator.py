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

    def execute(self, action, *, coords, coords_to=None):
        self.executed.append((action.kind, coords))
        return True

    def aborted(self): return self._aborted
    def is_dry_run(self): return self._dry
    def begin_command(self): pass


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


async def test_two_consecutive_harmless_commands_both_execute():
    """同じ Operator インスタンスで連続2コマンド: 予算リセットにより両方が実行されること。"""
    act = _Actuator()
    op = _op(act, confirm=False)
    await op.handle("その検索ボタンをクリックして", user_id=0)
    await op.handle("その検索ボタンをクリックして", user_id=0)
    assert len(act.executed) == 2


async def test_demonstrative_uses_original_utterance_as_instruction():
    """指示代名詞(target="")のとき、grounding に渡す instruction が元の発話になること。"""
    recorded: list[str] = []

    async def _ground_record(image_b64, *, instruction, region):
        recorded.append(instruction)
        return GroundResult(x=100, y=200, raw="click(100,200)")

    act = _Actuator()
    op = _op(act, ground=_ground_record, confirm=False)
    await op.handle("ここをクリックして", user_id=0)
    assert recorded == ["ここをクリックして"]


async def test_pending_ttl_expiry_discards_destructive():
    """TTL 切れ後に肯定応答しても pending が破棄され、実行されないこと。"""
    now = [0.0]

    def _clock():
        return now[0]

    act = _Actuator()
    op = Operator(
        ground=_ground_ok, capture_region=_cap, actuator=act, policy_cfg=CFG,
        get_foreground=lambda: "chrome.exe",
        pending_ttl_s=10.0,
        clock=_clock,
    )
    # ターン1: 破壊的コマンドで確認待ち状態へ
    first = await op.handle("送信ボタンをクリックして", user_id=0)
    assert act.executed == []
    assert first is not None and "確認" in first

    # TTL を超えてクロックを進める
    now[0] = 20.0

    # ターン2: 肯定応答でも pending が TTL 切れにより破棄され、実行されない
    second = await op.handle("うん", user_id=0)
    assert act.executed == []   # 実行されていないこと
    # "うん" は pending なし → parse_chain では [] → handle は None を返す
    assert second is None


# ---------------------------------------------------------------------------
# Task 5: chain execution, drag grounding, grounding self-check
# ---------------------------------------------------------------------------

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
