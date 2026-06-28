from kotoha.screen.sanitize import normalize_summary


def test_strips_markdown_emphasis_and_backticks():
    assert normalize_summary("画面に**99%**の`CPU`負荷。") == "画面に99%のCPU負荷。"


def test_strips_underscore_emphasis():
    assert normalize_summary("__強調__された文。") == "強調された文。"


def test_collapses_newlines_and_bullets():
    # 箇条書きの記号と改行を除き、句点区切りの平文へ詰める。
    assert normalize_summary("- 左にエディタ。\n- 右にブラウザ。") == "左にエディタ。右にブラウザ。"


def test_removes_heading_markers():
    assert normalize_summary("# 見出し。\n本文。") == "見出し。本文。"


def test_clamps_to_two_sentences_by_default():
    assert normalize_summary("一文目。二文目。三文目。") == "一文目。二文目。"


def test_clamp_is_configurable():
    assert normalize_summary("あ。い。う。", max_sentences=1) == "あ。"


def test_empty_or_blank_is_empty():
    assert normalize_summary("") == ""
    assert normalize_summary("   ") == ""
    assert normalize_summary(None) == ""


def test_unpunctuated_fragment_passes_through_lossless():
    assert normalize_summary("画面にエディタ") == "画面にエディタ"


def test_plain_two_sentences_unchanged():
    assert normalize_summary("画面にエディタ。横にブラウザ。") == "画面にエディタ。横にブラウザ。"
