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


def test_begin_command_resets_per_command_budget():
    b = _FakeBackend()
    act = Actuator(dry_run=False, kill_hotkey="ctrl+alt+q", max_actions=1, backend=b)
    assert act.execute(ActionRequest("click"), coords=(1, 1)) is True   # 1回目: ok
    assert act.execute(ActionRequest("click"), coords=(2, 2)) is False  # 予算切れ
    act.begin_command()
    assert act.execute(ActionRequest("click"), coords=(3, 3)) is True   # リセット後: ok


def test_begin_command_preserves_kill_latch():
    b = _FakeBackend()
    act = Actuator(dry_run=False, kill_hotkey="ctrl+alt+q", max_actions=5, backend=b)
    act._aborted = True
    act.begin_command()
    assert act.execute(ActionRequest("click"), coords=(1, 1)) is False  # kill ラッチは残る
