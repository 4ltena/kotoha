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
            logger.warning("failed to reach %s: %s", name, url)
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


async def _openai_ok(session, base_url: str) -> bool:
    """OpenAI 互換: GET /v1/models が 200 を返せば稼働とみなす。"""
    try:
        async with session.get(f"{base_url}/v1/models") as resp:
            return resp.status == 200
    except aiohttp.ClientError:
        return False


async def probe_llm_endpoint(session, base_url: str, *, api: str) -> bool:
    """LLM/VLM エンドポイントの到達確認。api='ollama' は /api/tags、それ以外は /v1/models。"""
    if api == "ollama":
        return await _ollama_ok(session, base_url)
    return await _openai_ok(session, base_url)


async def check_aux_endpoints(session, *, config) -> dict:
    """画面知覚が有効なとき、ollama_url と異なる知覚VLM・補助LLM だけ非致命に疎通確認する。

    主サービスのヘルスとは別。down でも会話は best-effort で続くため raise しない。
    ollama_url と同一のエンドポイントは主チェックで見ているので省く。
    """
    results = {}
    if not getattr(config, "screen_perception_enabled", False):
        return results
    vlm_url = config.vlm_perception_url or config.ollama_url
    if vlm_url != config.ollama_url:
        results["vlm"] = await probe_llm_endpoint(session, vlm_url, api=config.vlm_perception_api)
    aux_url = config.aux_llm_url or config.ollama_url
    if aux_url != config.ollama_url:
        # 補助LLM(記憶圧縮・関係性分析)は Ollama ネイティブ(/api/chat)を使う。
        results["aux"] = await _ollama_ok(session, aux_url)
    return results
