import logging

import aiohttp

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


async def _ollama_ok(session, base_url: str) -> bool:
    """Ollama: GET /api/tags が 200 を返せば稼働とみなす。"""
    try:
        async with session.get(f"{base_url}/api/tags") as resp:
            return resp.status == 200
    except aiohttp.ClientError:
        return False


async def _reachable(session, base_url: str) -> bool:
    """GPT-SoVITS: 専用ヘルスエンドポイントが無い。

    何らかの HTTP 応答(404/400 含む)が返れば到達可能とみなし、
    接続エラー(ClientError)のみ down とする。
    """
    try:
        async with session.get(f"{base_url}/") as resp:
            _ = resp.status   # 応答が返れば到達可能
            return True
    except aiohttp.ClientError:
        return False


async def check_local_services(session, *, ollama_url: str, gptsovits_url: str) -> dict:
    """ローカル構成(Ollama + GPT-SoVITS)の疎通を確認する。"""
    return {
        "ollama": await _ollama_ok(session, ollama_url),
        "gptsovits": await _reachable(session, gptsovits_url),
    }
