import logging

from kotoha.llm.front_client import stream_chat

logger = logging.getLogger(__name__)

_SYSTEM = (
    "次の会話から、後で思い出す価値のある事実だけを短い箇条書きで抽出する。"
    "雑談の流れや挨拶は省く。日本語で、1行1項目、最大数行。箇条書きのみを返す。"
)


def _format_turns(turns: list[dict]) -> str:
    lines = []
    for t in turns:
        who = "ユーザー" if t.get("role") == "user" else "ことは"
        lines.append(f"{who}: {t.get('content', '')}")
    return "\n".join(lines)


def build_compress_messages(turns: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _format_turns(turns)},
    ]


def parse_entries(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.strip().lstrip("-・*").strip()
        if s:
            out.append(s)
    return out


async def compress_turns(
    turns: list[dict],
    *,
    model: str,
    session,
    base_url: str,
    llm_stream=stream_chat,
) -> list[str]:
    """生ログを 4b で圧縮し、箇条書きエントリ list[str] を返す。"""
    messages = build_compress_messages(turns)
    buf = ""
    async for piece in llm_stream(messages, model=model, base_url=base_url, session=session):
        buf += piece
    return parse_entries(buf)
