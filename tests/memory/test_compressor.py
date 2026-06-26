import pytest
from kotoha.memory.compressor import parse_entries, compress_turns


def test_parse_entries_strips_bullets_and_blanks():
    text = "- ユーザーは犬が好き\n・猫も飼っている\n\n*  旅行が趣味\n   \n"
    assert parse_entries(text) == [
        "ユーザーは犬が好き", "猫も飼っている", "旅行が趣味",
    ]


async def test_compress_turns_joins_tokens_and_parses():
    captured = {}

    async def fake_llm(messages, *, model, base_url, session):
        captured["model"] = model
        captured["messages"] = messages
        for tok in ["- 事実1\n", "- 事実2"]:
            yield tok

    turns = [
        {"role": "user", "content": "犬を飼ってる"},
        {"role": "assistant", "content": "いいですね"},
    ]
    entries = await compress_turns(
        turns, model="qwen3.5:4b", session=None,
        base_url="http://x", llm_stream=fake_llm,
    )
    assert entries == ["事実1", "事実2"]
    assert captured["model"] == "qwen3.5:4b"
    # 生ログ本文がプロンプトに含まれる
    assert "犬を飼ってる" in captured["messages"][-1]["content"]
