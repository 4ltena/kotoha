import logging

logger = logging.getLogger(__name__)


async def check_services(session, *, ollama_url: str, tts_http_url: str) -> dict:
    """起動時の最小疎通チェック。プロセス再起動・常時ウォッチドッグはフェーズ1.x。"""
    results = {}
    for name, url in (("ollama", f"{ollama_url}/api/tags"),
                      ("tts_http", f"{tts_http_url}/version")):
        try:
            async with session.get(url) as r:
                results[name] = r.status == 200
        except Exception:
            logger.warning("%s への疎通に失敗: %s", name, url)
            results[name] = False
    return results
