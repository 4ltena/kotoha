from kotoha.relationship.store import RelationshipStore
from kotoha.relationship.analyzer import (
    parse_deltas,
    apply_deltas,
    analyze,
    DELTA_CLAMP,
)


def test_parse_deltas_extracts_and_clamps():
    out = parse_deltas('ええと {"affection": 2, "mood": -99, "trust": 1} かな')
    assert out["affection"] == 2
    assert out["mood"] == -DELTA_CLAMP      # 大きすぎる値は上限でクランプ
    assert out["trust"] == 1


def test_parse_deltas_bad_json():
    assert parse_deltas("JSONなし") == {}


def test_apply_deltas_clamps_to_ranges():
    s = RelationshipStore("x", affection=99, mood=49)
    apply_deltas(s, {"affection": 5, "mood": 5})
    assert s.affection == 100 and s.mood == 50   # 範囲上限でクランプ


def test_apply_deltas_lower_bound():
    s = RelationshipStore("x", trust=1, mood=-49)
    apply_deltas(s, {"trust": -5, "mood": -5})
    assert s.trust == 0 and s.mood == -50


async def test_analyze_calls_llm_and_parses():
    captured = {}

    async def fake_llm(messages, *, model, base_url, session):
        captured["model"] = model
        captured["user"] = messages[-1]["content"]
        for t in ['{"affection":', ' 1, "mood": -1}']:
            yield t

    s = RelationshipStore("x")
    out = await analyze(
        "好きだよ", s, model="qwen3.5:4b", session=None, base_url="x",
        context="東京は晴れ", llm_stream=fake_llm,
    )
    assert out == {"affection": 1, "mood": -1}
    assert captured["model"] == "qwen3.5:4b"
    assert "好きだよ" in captured["user"] and "晴れ" in captured["user"]
