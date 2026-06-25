import pytest
from talk_ai.llm.front_client import parse_chat_line, stream_chat


def test_parse_intermediate_chunk():
    line = (
        b'{"model":"llama3.2","created_at":"x",'
        b'"message":{"role":"assistant","content":"The"},"done":false}'
    )
    assert parse_chat_line(line) == ("The", False)


def test_parse_final_chunk():
    line = (
        b'{"model":"llama3.2","created_at":"y",'
        b'"message":{"role":"assistant","content":""},"done":true}'
    )
    assert parse_chat_line(line) == ("", True)


def test_parse_blank_line():
    assert parse_chat_line(b"  ") == ("", False)


@pytest.mark.integration
async def test_stream_chat_real_ollama():
    msgs = [{"role": "user", "content": "1と2を足すと?"}]
    pieces = []
    async for piece in stream_chat(msgs, model="qwen3.5:4b"):
        pieces.append(piece)
    assert "".join(pieces).strip() != ""


class _FakeContent:
    def __init__(self, lines):
        self._lines = lines

    def __aiter__(self):
        async def gen():
            for ln in self._lines:
                yield ln
        return gen()


class _FakeResp:
    def __init__(self, lines):
        self.content = _FakeContent(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, lines):
        self._lines = lines
        self.posts = []

    def post(self, url, *, json=None):
        self.posts.append((url, json))
        return _FakeResp(self._lines)


async def test_stream_chat_sends_think_false_and_streams():
    lines = [
        '{"message":{"content":"はい"},"done":false}'.encode(),
        b'{"message":{"content":""},"done":true}',
    ]
    sess = _FakeSession(lines)
    pieces = []
    async for p in stream_chat(
        [{"role": "user", "content": "x"}], model="qwen3.5:4b", session=sess
    ):
        pieces.append(p)
    assert pieces == ["はい"]
    url, payload = sess.posts[0]
    assert url.endswith("/api/chat")
    assert payload["model"] == "qwen3.5:4b"
    assert payload["stream"] is True
    assert payload["think"] is False
    assert payload["messages"] == [{"role": "user", "content": "x"}]
