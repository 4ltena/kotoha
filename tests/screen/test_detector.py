from kotoha.screen.detector import is_game_active, resolve_mode, is_borderless_fullscreen


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


def test_borderless_fullscreen_covers_its_monitor():
    mon = (0, 0, 1920, 1080)
    assert is_borderless_fullscreen((0, 0, 1920, 1080), mon, maximized=False) is True


def test_borderless_fullscreen_on_secondary_monitor():
    mon = (1920, 0, 3840, 1080)   # 右隣のサブモニタ。プライマリ限定だと取りこぼす
    assert is_borderless_fullscreen((1920, 0, 3840, 1080), mon, maximized=False) is True


def test_maximized_window_is_not_fullscreen():
    mon = (0, 0, 1920, 1080)
    # タスクバー自動非表示で窓が画面を覆っても、WS_MAXIMIZE なら除外。
    assert is_borderless_fullscreen((-8, -8, 1928, 1088), mon, maximized=True) is False


def test_windowed_is_not_fullscreen():
    mon = (0, 0, 1920, 1080)
    assert is_borderless_fullscreen((100, 100, 800, 600), mon, maximized=False) is False
