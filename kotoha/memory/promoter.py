import logging

from kotoha.memory.discovery import GEMINI_BASE

logger = logging.getLogger(__name__)


class AllModelsFailed(Exception):
    """候補チェーンの全モデルが失敗した。"""


def build_promote_prompt(long_term: str, entries: list[str]) -> str:
    bullets = "\n".join("- " + e for e in entries)
    return (
        "あなたはキャラクター「ことは」の長期記憶を編集する。"
        "既存の長期記憶と新しい短期メモを統合し、重複を消し、"
        "重要なユーザー像・好み・価値観・関係性に絞って簡潔な日本語にまとめ直す。"
        "ことはの核（名前・口調）は変更しない。"
        "ただしユーザーに合わせて性格のニュアンスはごく少しずつ寄せてよい。"
        "長期記憶の本文だけを返す。\n\n"
        f"# 既存の長期記憶\n{long_term or '(空)'}\n\n"
        f"# 新しい短期メモ\n{bullets}\n"
    )


def _make_gemini_generate(*, api_key: str, session, base_url: str):
    async def generate(model: str, prompt: str) -> str:
        url = f"{base_url}/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        async with session.post(url, json=payload) as resp:
            resp.raise_for_status()   # 429/4xx/5xx は例外 -> 次候補へ
            data = await resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    return generate


async def promote(
    long_term: str,
    entries: list[str],
    *,
    model_chain: list[str],
    api_key: str,
    session,
    base_url: str = GEMINI_BASE,
    generate=None,
) -> str:
    """候補チェーンを順に試し、最初に成功したモデルの統合結果を返す。"""
    if generate is None:
        generate = _make_gemini_generate(
            api_key=api_key, session=session, base_url=base_url
        )
    prompt = build_promote_prompt(long_term, entries)
    for model in model_chain:
        try:
            return await generate(model, prompt)
        except Exception as e:   # noqa: BLE001 - 次候補へフォールバック
            logger.warning("gemini model %s failed (%s); trying next", model, e)
    raise AllModelsFailed(f"all models failed: {model_chain}")
