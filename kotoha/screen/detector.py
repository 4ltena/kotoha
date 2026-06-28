"""ゲーム起動の判定。前面窓のフルスクリーン検知とプロセス名リストを併用する。

判定本体は純関数。前面窓情報の取得だけ OS 依存(get_foreground_info)で、注入で渡す。
"""

import logging

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
