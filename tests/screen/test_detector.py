from kotoha.screen.detector import is_game_active, resolve_mode


def test_none_foreground_is_not_game():
    assert is_game_active(None, detect_fullscreen=True, process_names=()) is False


def test_fullscreen_only():
    fg = {"fullscreen": True, "process": "vlc.exe"}
    assert is_game_active(fg, detect_fullscreen=True, process_names=()) is True
    assert is_game_active(fg, detect_fullscreen=False, process_names=()) is False


def test_process_list_matches_substring_case_insensitive():
    fg = {"fullscreen": False, "process": "C:/Games/EldenRing.exe"}
    assert is_game_active(fg, detect_fullscreen=False, process_names=("eldenring",)) is True
    assert is_game_active(fg, detect_fullscreen=False, process_names=("doom",)) is False


def test_resolve_mode():
    assert resolve_mode(False, "powersave") == "normal"
    assert resolve_mode(True, "powersave") == "game_powersave"
    assert resolve_mode(True, "realtime") == "game_realtime"
    assert resolve_mode(True, "anything-else") == "game_powersave"  # 既定は省力型
