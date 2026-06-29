from kotoha.llm import persona


def test_persona_mentions_operation_behavior():
    p = persona.SYSTEM_PROMPT
    assert "操作" in p and "確認" in p and "失敗" in p
