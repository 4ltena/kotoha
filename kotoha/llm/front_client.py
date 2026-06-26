import json
from typing import AsyncIterator

import aiohttp


def parse_chat_line(line: bytes) -> tuple[str, bool]:
    """Ollama /api/chat の NDJSON 1 行を (content_piece, done) に変換。
    トークンは obj['message']['content'](ネスト)、終了は top-level 'done'。"""
    line = line.strip()
    if not line:
        return "", False
    obj = json.loads(line)
    piece = obj.get("message", {}).get("content", "")
    return piece, bool(obj.get("done"))


async def stream_chat(
    messages: list[dict],
    *,
    model: str,
    base_url: str = "http://localhost:11434",
    session: aiohttp.ClientSession | None = None,
    think: bool = False,
    num_predict: int | None = None,
) -> AsyncIterator[str]:
    """増分トークン文字列を yield。タスク cancel で接続が閉じ生成停止。
    session を渡せば長命の共有接続を使う(渡さなければ都度生成・破棄)。
    num_predict を渡すと生成トークン数を上限で打ち切る(独白・冗長応答の抑制)。"""
    payload = {"model": model, "messages": messages, "stream": True, "think": think}
    if num_predict is not None:
        payload["options"] = {"num_predict": num_predict}
    timeout = aiohttp.ClientTimeout(total=None, sock_read=300)
    own = session is None
    sess = session or aiohttp.ClientSession(timeout=timeout)
    try:
        async with sess.post(f"{base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for raw in resp.content:   # NDJSON: 1 行 = 1 JSON
                piece, done = parse_chat_line(raw)
                if piece:
                    yield piece
                if done:
                    return
    finally:
        if own:
            await sess.close()
