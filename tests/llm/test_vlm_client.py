from kotoha.llm.vlm_client import build_vlm_payload, parse_vlm_response


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
