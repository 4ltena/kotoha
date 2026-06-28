"""ゲーム起動の判定。前面窓のフルスクリーン検知とプロセス名リストを併用する。

判定本体は純関数。前面窓情報の取得だけ OS 依存(get_foreground_info)で、注入で渡す。
"""

import asyncio
import logging
import sys

logger = logging.getLogger(__name__)


def is_game_active(foreground, *, detect_fullscreen: bool, process_names) -> bool:
    """foreground={"fullscreen": bool, "process": str} か None。"""
    if not foreground:
        return False
    name = (foreground.get("process") or "").lower()
    names = tuple(n.lower() for n in (process_names or ()))
    if names and name and any(n in name for n in names):
        return True
    if detect_fullscreen and foreground.get("fullscreen"):
        return True
    return False


def resolve_mode(is_game: bool, game_mode: str) -> str:
    """ゲーム判定と設定から現在モードを決める。"""
    if not is_game:
        return "normal"
    return "game_realtime" if game_mode == "realtime" else "game_powersave"


def is_borderless_fullscreen(win, mon, *, maximized: bool) -> bool:
    """前面窓がその窓のあるモニタを覆うか(純関数)。最大化ウィンドウは除外する。

    win/mon は (left, top, right, bottom)。プライマリ解像度ではなく**窓が乗っている
    モニタ**の矩形と比べることで、サブモニタのボーダレスゲームを取りこぼさない。
    タスクバー自動非表示の最大化通常窓を誤検出しないよう WS_MAXIMIZE は除く。
    """
    if maximized:
        return False
    return (win[0] <= mon[0] and win[1] <= mon[1]
            and win[2] >= mon[2] and win[3] >= mon[3])


def get_foreground_info():
    """前面窓の {"fullscreen": bool, "process": str} を返す(Windows)。失敗・非対応は None。

    ctypes で前面窓の矩形を、その窓が乗っているモニタの矩形と比べ、プロセス名を取得する
    best-effort。判定本体は is_borderless_fullscreen(純関数)に委ねる。
    """
    if sys.platform != "win32":
        return None   # 非Windowsでは静かに諦める(毎ポール tracebackを出さない)
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        win = (rect.left, rect.top, rect.right, rect.bottom)

        # 窓が乗っているモニタの矩形を取る(プライマリ限定をやめる)。
        MONITOR_DEFAULTTONEAREST = 2
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            m = mi.rcMonitor
            mon = (m.left, m.top, m.right, m.bottom)
        else:
            sw = user32.GetSystemMetrics(0)   # SM_CXSCREEN フォールバック
            sh = user32.GetSystemMetrics(1)
            mon = (0, 0, sw, sh)

        # 最大化(WS_MAXIMIZE)を除外して、本当のボーダレスフルスクリーンだけ拾う。
        GWL_STYLE = -16
        WS_MAXIMIZE = 0x01000000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        maximized = bool(style & WS_MAXIMIZE)

        fullscreen = is_borderless_fullscreen(win, mon, maximized=maximized)

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = buf.value
            finally:
                kernel32.CloseHandle(h)
        return {"fullscreen": bool(fullscreen), "process": name}
    except Exception:
        logger.warning("get_foreground_info failed", exc_info=True)
        return None


class GameModeLoop:
    """前面窓を定期監視し、ゲーム判定の結果を ScreenContext のモードへ反映する。"""

    def __init__(self, *, screen_ctx, config, get_foreground=get_foreground_info,
                 sleep=asyncio.sleep):
        self._ctx = screen_ctx
        self._config = config
        self._get_foreground = get_foreground
        self._sleep = sleep
        self._stop = False

    async def tick(self) -> None:
        try:
            fg = self._get_foreground()
        except Exception:
            logger.warning("foreground probe failed", exc_info=True)
            return
        active = is_game_active(
            fg,
            detect_fullscreen=self._config.screen_game_detect_fullscreen,
            process_names=self._config.screen_game_process_names,
        )
        self._ctx.set_mode(resolve_mode(active, self._config.screen_game_mode))

    async def run(self) -> None:
        while not self._stop:
            await self.tick()
            await self._sleep(self._config.screen_game_poll_s)

    def stop(self) -> None:
        self._stop = True
