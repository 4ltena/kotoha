from datetime import datetime

from kotoha.memory.composer import build_messages, format_time_context


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


def test_format_time_context_bands():
    assert "朝" in format_time_context(datetime(2026, 6, 27, 7, 30))
    assert "昼" in format_time_context(datetime(2026, 6, 27, 13, 0))
    assert "夕方" in format_time_context(datetime(2026, 6, 27, 18, 0))
    assert "夜" in format_time_context(datetime(2026, 6, 27, 21, 0))
    assert "深夜" in format_time_context(datetime(2026, 6, 27, 2, 0))
    s = format_time_context(datetime(2026, 6, 27, 21, 5))
    assert "2026-06-27" in s and "21:05" in s


def test_time_context_block_included_after_immutable_and_omitted_when_empty():
    with_tc = build_messages(
        immutable="不変テキスト", long_term="ユーザーは犬好き",
        short_term=[], raw_window=[], time_context="現在は夜です。",
    )[0]["content"]
    assert "いまの時刻" in with_tc and "現在は夜です。" in with_tc
    # 不変の後・長期の前に入る
    assert with_tc.index("不変テキスト") < with_tc.index("現在は夜です。") < with_tc.index("ユーザーは犬好き")

    without = build_messages(
        immutable="不変テキスト", long_term="", short_term=[], raw_window=[],
    )[0]["content"]
    assert "いまの時刻" not in without
