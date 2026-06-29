from kotoha.config import Config
from kotoha.operate.actions import ActionRequest, is_affirmative, is_negative, parse_chain, parse_intent

CFG = Config()


def test_click_extracts_target():
    a = parse_intent("その検索ボタンをクリックして", config=CFG)
    assert a == ActionRequest(kind="click", target="その検索ボタン")


def test_demonstrative_only_target_is_blank():
    a = parse_intent("ここを押して", config=CFG)
    assert a.kind == "click" and a.target == ""


def test_right_click_before_click():
    a = parse_intent("そのファイルを右クリックして", config=CFG)
    assert a.kind == "right_click" and a.target == "そのファイル"


def test_double_click_on_open():
    a = parse_intent("そのフォルダを開いて", config=CFG)
    assert a.kind == "double_click" and a.target == "そのフォルダ"


def test_type_extracts_quoted_text():
    a = parse_intent("「こんにちは」と入力して", config=CFG)
    assert a.kind == "type" and a.text == "こんにちは"


def test_scroll_direction():
    assert parse_intent("下にスクロール", config=CFG).amount < 0
    assert parse_intent("上にスクロール", config=CFG).amount > 0


def test_hotkey_from_map():
    a = parse_intent("保存して", config=CFG)
    assert a.kind == "hotkey" and a.keys == "ctrl+s"


def test_no_intent_passes_through():
    assert parse_intent("今日は疲れたな", config=CFG) is None


def test_affirmative_and_negation_priority():
    assert is_affirmative("うん") is True
    assert is_negative("やめて") is True
    assert is_affirmative("そうじゃない") is False   # 否定優先


def test_page_up_scroll_positive_amount():
    assert parse_intent("ページアップ", config=CFG).amount > 0


def test_drag_extracts_from_and_to():
    a = parse_intent("ファイルをゴミ箱にドラッグして", config=CFG)
    assert a.kind == "drag" and a.target == "ファイル" and a.to_target == "ゴミ箱"


def test_drag_requires_both_targets():
    # 「を…に」が揃わない曖昧な発話は drag にしない
    assert parse_intent("ドラッグして", config=CFG) is None


def test_chain_splits_on_connectors():
    actions = parse_chain("検索ボタンを押して、それから送信ボタンを押して", config=CFG)
    assert len(actions) == 2
    assert actions[0].target == "検索ボタン" and actions[1].target == "送信ボタン"


def test_chain_protects_quoted_comma():
    # 引用内の 、 で分割しない: 型入力 + 1操作 = 2節
    actions = parse_chain("「a、b」と入力して、検索ボタンを押して", config=CFG)
    assert len(actions) == 2
    assert actions[0].kind == "type" and actions[0].text == "a、b"
    assert actions[1].kind == "click"


def test_chain_single_clause():
    actions = parse_chain("検索ボタンを押して", config=CFG)
    assert len(actions) == 1 and actions[0].kind == "click"


def test_chain_empty_on_no_intent():
    assert parse_chain("今日はいい天気", config=CFG) == []
