from kotoha.llm import persona


def test_build_messages_prepends_system():
    history = [{"role": "user", "content": "やあ"}]
    msgs = persona.build_messages(history)
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == persona.SYSTEM_PROMPT
    assert msgs[1:] == history


def test_build_messages_does_not_mutate_input():
    history = [{"role": "user", "content": "x"}]
    persona.build_messages(history)
    assert history == [{"role": "user", "content": "x"}]


def test_immutable_prompt_is_system_prompt_alias():
    assert persona.IMMUTABLE_PROMPT == persona.SYSTEM_PROMPT
    assert "ことは" in persona.IMMUTABLE_PROMPT
    assert "わたし" in persona.IMMUTABLE_PROMPT
