from kotoha.memory.discovery import order_by_priority


def test_order_by_priority_groups_in_priority_order():
    names = [
        "gemini-2.0-flash", "gemini-2.0-flash-lite",
        "gemini-1.5-pro", "gemma-3-4b",
    ]
    out = order_by_priority(names, ("flash-lite", "flash", "gemma"))
    # flash-lite 群 -> flash 群 -> gemma 群。pro は除外。
    assert out == ["gemini-2.0-flash-lite", "gemini-2.0-flash", "gemma-3-4b"]


def test_order_by_priority_no_match_returns_empty():
    assert order_by_priority(["gemini-1.5-pro"], ("flash", "gemma")) == []


def test_order_by_priority_dedupes():
    # flash-lite は "flash" にも部分一致するが二重に入れない
    out = order_by_priority(["gemini-2.0-flash-lite"], ("flash-lite", "flash"))
    assert out == ["gemini-2.0-flash-lite"]
