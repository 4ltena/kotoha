import urllib.request

import pytest

pytestmark = pytest.mark.integration


def _ollama_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


async def test_capture_describe_returns_summary_real_vlm():
    pytest.importorskip("PIL")
    pytest.importorskip("mss")
    import aiohttp

    from kotoha.config import build_config
    from kotoha.llm.vlm_client import vlm_describe
    from kotoha.screen.capture import MssCapturer
    from kotoha.screen.sanitize import normalize_summary

    config = build_config()
    if not _ollama_reachable(config.ollama_url):
        pytest.skip("Ollama not reachable")
    img = MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture()
    if not img:
        pytest.skip("screen capture unavailable")
    async with aiohttp.ClientSession() as session:
        summary = await vlm_describe(
            img, model=config.vlm_perception_model,
            base_url=config.vlm_perception_url or config.ollama_url,
            prompt=config.vlm_perception_prompt, api=config.vlm_perception_api,
            session=session, timeout_s=60.0,
        )
    assert normalize_summary(summary)   # 実 VLM が非空の要約を返す


async def test_perception_to_orchestrator_injection_end_to_end():
    pytest.importorskip("PIL")
    pytest.importorskip("mss")
    import aiohttp
    import numpy as np

    from kotoha.config import build_config
    from kotoha.llm import persona
    from kotoha.llm.vlm_client import vlm_describe
    from kotoha.orchestrator import Orchestrator
    from kotoha.screen.capture import MssCapturer
    from kotoha.screen.sanitize import normalize_summary
    from kotoha.screen.state import ScreenContext

    config = build_config()
    if not _ollama_reachable(config.ollama_url):
        pytest.skip("Ollama not reachable")
    img = MssCapturer(max_long_edge=config.screen_capture_max_long_edge).capture()
    if not img:
        pytest.skip("screen capture unavailable")
    async with aiohttp.ClientSession() as session:
        summary = await vlm_describe(
            img, model=config.vlm_perception_model,
            base_url=config.vlm_perception_url or config.ollama_url,
            prompt=config.vlm_perception_prompt, api=config.vlm_perception_api,
            session=session, timeout_s=60.0,
        )
    ctx = ScreenContext()
    ctx.set_summary(normalize_summary(summary))

    captured = []

    def llm(messages, *, model):
        captured.append([dict(m) for m in messages])

        async def gen():
            yield "はい。"

        return gen()

    async def tts(text):
        return b""

    class _Tr:
        def transcribe(self, audio):
            return "いまどう?"

    class _Player:
        def is_playing(self):
            return False

        def stop(self):
            pass

        async def play_and_wait(self, wav):
            return True

    orch = Orchestrator(
        transcriber=_Tr(), llm_stream=llm, tts=tts, player=_Player(),
        model="m", vad_factory=lambda: object(), persona=persona, screen_context=ctx,
    )
    await orch.handle_utterance(0, np.zeros(16000, dtype=np.float32))
    contents = [m["content"] for m in captured[0] if m["role"] == "system"]
    assert any(c.startswith("【画面の様子】") for c in contents)
    assert any(ctx.get_summary() in c for c in contents)   # 実要約が注入される
