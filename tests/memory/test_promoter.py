import pytest
from kotoha.memory.promoter import promote, build_promote_prompt, AllModelsFailed


def test_build_promote_prompt_contains_inputs():
    p = build_promote_prompt("既存ユーザー像", ["新事実A", "新事実B"])
    assert "既存ユーザー像" in p
    assert "新事実A" in p and "新事実B" in p
    assert "つくよみ" in p   # 核を変えない旨の指示


async def test_promote_uses_first_model_on_success():
    calls = []

    async def fake_generate(model, prompt):
        calls.append(model)
        return "統合後の長期記憶"

    out = await promote(
        "old", ["a", "b"], model_chain=["m1", "m2"],
        api_key="k", session=None, generate=fake_generate,
    )
    assert out == "統合後の長期記憶"
    assert calls == ["m1"]   # 先頭で成功したら次は呼ばない


async def test_promote_falls_back_then_raises():
    calls = []

    async def fail_generate(model, prompt):
        calls.append(model)
        raise RuntimeError("429")

    with pytest.raises(AllModelsFailed):
        await promote(
            "old", ["a"], model_chain=["m1", "m2"],
            api_key="k", session=None, generate=fail_generate,
        )
    assert calls == ["m1", "m2"]   # 全候補を順に試す
