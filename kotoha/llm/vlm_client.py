"""画像つき推論クライアント。Ollama /api/chat と OpenAI 互換 /v1/chat/completions の両対応。

リクエスト生成と応答解析は純関数(front_client の parse_chat_line と同じ流儀)。
要約は短い日本語になるよう prompt 側で制約する。best-effort。
"""

import aiohttp


def build_vlm_payload(image_b64: str, *, prompt: str, model: str, api: str) -> tuple[str, dict]:
    """(path, payload) を返す。api は "openai" | "ollama"。"""
    if api == "ollama":
        return "/api/chat", {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        }
    data_uri = f"data:image/jpeg;base64,{image_b64}"
    return "/v1/chat/completions", {
        "model": model,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }],
    }


def parse_vlm_response(obj: dict, *, api: str) -> str:
    if api == "ollama":
        return (obj.get("message", {}).get("content") or "").strip()
    choices = obj.get("choices") or []
    if not choices:
        return ""
    return (choices[0].get("message", {}).get("content") or "").strip()


async def vlm_describe(
    image_b64: str,
    *,
    model: str,
    base_url: str,
    prompt: str,
    api: str = "openai",
    session: aiohttp.ClientSession,
    timeout_s: float = 20.0,
) -> str:
    """画像を VLM へ送り、短い要約文字列を返す。失敗は例外を投げる(呼び出し側で捕捉)。"""
    path, payload = build_vlm_payload(image_b64, prompt=prompt, model=model, api=api)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with session.post(f"{base_url}{path}", json=payload, timeout=timeout) as resp:
        resp.raise_for_status()
        obj = await resp.json()
    return parse_vlm_response(obj, api=api)
