import pytest

from kotoha.llm.vlm_client import build_vlm_payload, parse_vlm_response, vlm_describe


def test_build_payload_openai():
    path, payload = build_vlm_payload("ZZZ", prompt="説明して", model="qwen3-vl:4b", api="openai")
    assert path == "/v1/chat/completions"
    assert payload["model"] == "qwen3-vl:4b"
    assert payload["stream"] is False
    content = payload["messages"][0]["content"]
    assert {"type": "text", "text": "説明して"} in content
    img = [c for c in content if c["type"] == "image_url"][0]
    assert img["image_url"]["url"] == "data:image/jpeg;base64,ZZZ"


def test_build_payload_ollama():
    path, payload = build_vlm_payload("ZZZ", prompt="説明して", model="qwen3-vl:4b", api="ollama")
    assert path == "/api/chat"
    msg = payload["messages"][0]
    assert msg["content"] == "説明して"
    assert msg["images"] == ["ZZZ"]
    assert payload["stream"] is False


def test_parse_response_openai():
    obj = {"choices": [{"message": {"content": "  画面にコード。 "}}]}
    assert parse_vlm_response(obj, api="openai") == "画面にコード。"


def test_parse_response_ollama():
    obj = {"message": {"content": "画面にブラウザ。"}}
    assert parse_vlm_response(obj, api="ollama") == "画面にブラウザ。"


def test_parse_response_empty():
    assert parse_vlm_response({"choices": []}, api="openai") == ""
    assert parse_vlm_response({}, api="ollama") == ""


class _FakeResp:
    def __init__(self, obj):
        self._obj = obj
        self.raised = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def raise_for_status(self):
        self.raised = True

    async def json(self):
        assert self.raised, "raise_for_status は json の前に呼ぶこと"
        return self._obj


class _FakeSession:
    def __init__(self, obj):
        self._obj = obj
        self.calls = []
        self.last = None

    def post(self, url, *, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        self.last = _FakeResp(self._obj)
        return self.last


async def test_vlm_describe_openai_posts_and_parses():
    sess = _FakeSession({"choices": [{"message": {"content": " 画面にエディタ。 "}}]})
    out = await vlm_describe(
        "B64", model="m", base_url="http://x:1", prompt="p",
        api="openai", session=sess, timeout_s=5.0,
    )
    assert out == "画面にエディタ。"
    assert sess.calls[0]["url"] == "http://x:1/v1/chat/completions"
    assert sess.calls[0]["json"]["model"] == "m"
    assert sess.last.raised is True   # raise_for_status を通している


async def test_vlm_describe_ollama_path():
    sess = _FakeSession({"message": {"content": "画面にブラウザ。"}})
    out = await vlm_describe(
        "B64", model="m", base_url="http://x:1", prompt="p",
        api="ollama", session=sess, timeout_s=5.0,
    )
    assert out == "画面にブラウザ。"
    assert sess.calls[0]["url"] == "http://x:1/api/chat"
