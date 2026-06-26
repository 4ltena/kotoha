from kotoha.llm.think_filter import ThinkFilter


def _run(pieces):
    """pieces を順に push し、最後に flush した連結結果を返す。"""
    f = ThinkFilter()
    out = "".join(f.push(p) for p in pieces)
    return out + f.flush()


def test_passthrough_without_think():
    assert _run(["はい", "、", "元気", "です。"]) == "はい、元気です。"


def test_removes_think_span_single_chunk():
    assert _run(["<think>あれこれ考える</think>こんにちは"]) == "こんにちは"


def test_removes_empty_think():
    assert _run(["<think></think>はい"]) == "はい"


def test_think_split_across_chunks():
    # タグも思考本文もチャンク境界で分割される
    pieces = ["ね", "<th", "ink>な", "やむ", "</thi", "nk>了解", "です"]
    assert _run(pieces) == "ね了解です"


def test_text_before_and_after_think():
    assert _run(["まず", "<think>", "考", "</think>", "次に"]) == "まず次に"


def test_unterminated_think_is_discarded_on_flush():
    # 終了タグが来ないまま終わったら think 内は破棄
    assert _run(["はい<think>まだ考え中"]) == "はい"


def test_lone_lt_is_not_swallowed_on_flush():
    # "<" は <think> の部分一致で保留されるが、タグにならなければ flush で出る
    assert _run(["1 < 2"]) == "1 < 2"


def test_partial_open_tag_then_real_text():
    # "<thi" の後に think でない文字が来たら通常テキストとして戻る
    assert _run(["<thi", "s is fine"]) == "<this is fine"
