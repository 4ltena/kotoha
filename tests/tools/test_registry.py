from kotoha.config import Config
from kotoha.tools.registry import api_search


async def test_api_search_returns_first_hit():
    async def p_none(text, *, session, config):
        return None

    async def p_hit(text, *, session, config):
        return "結果A"

    async def p_other(text, *, session, config):
        return "結果B"

    out = await api_search(
        "x", session=None, config=Config(), providers=(p_none, p_hit, p_other)
    )
    assert out == "結果A"   # 最初の非 None


async def test_api_search_none_when_all_miss():
    async def p_none(text, *, session, config):
        return None

    out = await api_search("x", session=None, config=Config(), providers=(p_none,))
    assert out is None
