from kotoha.memory.composer import build_messages


def test_system_first_and_raw_window_follows():
    msgs = build_messages(
        immutable="不変テキスト",
        long_term="ユーザーは犬好き",
        short_term=["今日は雨", "テスト中"],
        raw_window=[{"role": "user", "content": "やあ"}],
    )
    assert msgs[0]["role"] == "system"
    assert msgs[1:] == [{"role": "user", "content": "やあ"}]
    sys = msgs[0]["content"]
    assert "不変テキスト" in sys
    assert "ユーザーは犬好き" in sys
    assert "今日は雨" in sys and "テスト中" in sys
    # 不変が長期より前、長期が短期より前
    assert sys.index("不変テキスト") < sys.index("ユーザーは犬好き") < sys.index("今日は雨")


def test_empty_long_and_short_blocks_omitted():
    msgs = build_messages(
        immutable="不変テキスト", long_term="", short_term=[], raw_window=[],
    )
    sys = msgs[0]["content"]
    assert "不変テキスト" in sys
    assert "覚えていること" not in sys     # 長期ブロック見出しが出ない
    assert "出てきたこと" not in sys       # 短期ブロック見出しが出ない
    assert msgs[1:] == []
