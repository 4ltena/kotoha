from kotoha.operate.actions import ActionRequest
from kotoha.operate.policy import app_allowed, is_destructive

KW = ("送信", "削除")


def test_destructive_by_keyword():
    a = ActionRequest("click", target="送信ボタン")
    assert is_destructive(a, destructive_keywords=KW, hotkeys_always=True) is True


def test_hotkey_always_destructive():
    a = ActionRequest("hotkey", keys="ctrl+s")
    assert is_destructive(a, destructive_keywords=(), hotkeys_always=True) is True


def test_harmless_click_not_destructive():
    a = ActionRequest("click", target="検索ボタン")
    assert is_destructive(a, destructive_keywords=KW, hotkeys_always=True) is False


def test_empty_allowlist_denies_all():
    assert app_allowed("chrome.exe", allowlist=()) is False


def test_allowlist_basename_lowercase_match():
    assert app_allowed("C:\\\\Program Files\\\\Chrome.exe", allowlist=("chrome.exe",)) is True
    assert app_allowed("/usr/bin/code", allowlist=("code",)) is True
    assert app_allowed("notepad.exe", allowlist=("chrome.exe",)) is False
