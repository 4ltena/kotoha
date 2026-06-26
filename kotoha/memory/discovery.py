import logging

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def order_by_priority(names: list[str], priority) -> list[str]:
    """priority パターン順に部分一致するモデル名を集める(重複排除)。"""
    out: list[str] = []
    seen: set[str] = set()
    for pat in priority:
        for name in names:
            if pat in name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


async def discover_gemini_models(
    api_key: str,
    *,
    priority,
    session,
    base_url: str = GEMINI_BASE,
) -> list[str]:
    """ListModels を1回叩き、優先順の軽量モデル候補チェーンを返す。"""
    url = f"{base_url}/models?key={api_key}"
    async with session.get(url) as resp:
        resp.raise_for_status()
        data = await resp.json()
    names = [
        m.get("name", "").split("/", 1)[-1]   # "models/xxx" -> "xxx"
        for m in data.get("models", [])
    ]
    names = [n for n in names if n]
    return order_by_priority(names, priority)
