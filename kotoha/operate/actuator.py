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
    if k == "drag":
        return f"drag {coords}->{getattr(action, 'to_target', '')}"
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

    def drag(self, x1, y1, x2, y2):
        self._pg.moveTo(x1, y1)
        self._pg.dragTo(x2, y2, duration=0.3)


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

    def begin_command(self) -> None:
        """次のコマンドのために動作カウントだけ戻す。kill ラッチ(_aborted)は保持する。"""
        self._count = 0

    def execute(self, action, *, coords, coords_to=None) -> bool:
        if self._aborted or self._count >= self._max_actions:
            return False
        self._count += 1
        try:
            if self._dry_run:
                logger.info("[dry-run] %s", _describe_action(action, coords))
                return True
            return self._do(action, coords, coords_to)
        except Exception:
            logger.warning("actuation failed", exc_info=True)
            return False

    def _do(self, action, coords, coords_to=None) -> bool:
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
        elif k == "drag":
            b.drag(coords[0], coords[1], coords_to[0], coords_to[1])
        else:
            return False
        return True

    def close(self) -> None:
        if self._keyboard is not None:
            try:
                self._keyboard.remove_hotkey(self._kill_hotkey)
            except Exception:
                logger.warning("kill hotkey removal failed", exc_info=True)
