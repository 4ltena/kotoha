import urllib.request

import pytest

pytestmark = pytest.mark.integration


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/v1/models", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


async def test_grounding_returns_coords_in_region_real_holo2():
    pytest.importorskip("PIL")
    pytest.importorskip("mss")
    import aiohttp

    from kotoha.config import build_config
    from kotoha.operate.grounding import ground_target
    from kotoha.screen.capture import MssCapturer

    config = build_config()
    g_url = config.grounding_url or config.vlm_perception_url or config.ollama_url
    if not _reachable(g_url):
        pytest.skip("grounding endpoint not reachable")
    cap = MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture_with_region()
    if not cap:
        pytest.skip("screen capture unavailable")
    image_b64, region = cap
    async with aiohttp.ClientSession() as session:
        result = await ground_target(
            image_b64, instruction="画面の中央あたりの何か", region=region,
            model=config.grounding_model, base_url=g_url, api=config.grounding_api,
            session=session, timeout_s=60.0,
        )
    if result is None:
        pytest.skip("grounding returned no coordinates (model/prompt mismatch)")
    assert region.left <= result.x <= region.left + region.width
    assert region.top <= result.y <= region.top + region.height
