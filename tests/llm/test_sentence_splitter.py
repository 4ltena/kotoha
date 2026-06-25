from kotoha.llm.sentence_splitter import SentenceSplitter


def test_emits_sentence_on_japanese_period():
    s = SentenceSplitter()
    assert s.push("こんにちは") == []
    assert s.push("。元気") == ["こんにちは。"]
    assert s.push("ですか?") == ["元気ですか?"]


def test_multiple_sentences_in_one_token():
    s = SentenceSplitter()
    assert s.push("はい。いいえ。") == ["はい。", "いいえ。"]


def test_flush_returns_remainder():
    s = SentenceSplitter()
    s.push("途中まで")
    assert s.flush() == "途中まで"
    assert s.flush() == ""


def test_whitespace_only_buffer_not_emitted():
    s = SentenceSplitter()
    assert s.push("  \n") == []
