"""操作の安全ポリシー判定（純関数）。破壊的かどうかと、前面アプリが許可されているか。"""


def is_destructive(action, *, destructive_keywords, hotkeys_always) -> bool:
    """破壊的なら True。hotkey は hotkeys_always で常に True。保守的に過剰確認側へ倒す。"""
    if action.kind == "hotkey" and hotkeys_always:
        return True
    hay = (action.target + " " + action.text).lower()
    return any(kw.lower() in hay for kw in destructive_keywords)


def app_allowed(foreground_process, *, allowlist) -> bool:
    """allowlist が空なら全拒否。非空なら前面プロセスの basename 小文字完全一致で判定。"""
    if not allowlist:
        return False
    name = (foreground_process or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    return name in {a.lower() for a in allowlist}
