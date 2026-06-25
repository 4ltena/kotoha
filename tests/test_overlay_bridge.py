from kotoha.overlay_bridge import OverlayBridge


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_str(self, s):
        self.sent.append(s)


class _BadWS:
    async def send_str(self, s):
        raise RuntimeError("closed")


async def test_broadcast_sends_json_to_clients():
    b = OverlayBridge()
    ws = _FakeWS()
    b._clients.add(ws)
    await b._broadcast({"type": "state", "value": "speaking"})
    assert ws.sent == ['{"type": "state", "value": "speaking"}']


async def test_broadcast_no_clients_is_noop():
    b = OverlayBridge()
    await b._broadcast({"type": "mouth", "value": 0.5})   # 例外を出さない


async def test_broadcast_drops_failed_client():
    b = OverlayBridge()
    bad = _BadWS()
    b._clients.add(bad)
    await b._broadcast({"type": "state", "value": "idle"})
    assert bad not in b._clients


def test_state_and_mouth_without_loop_are_safe():
    b = OverlayBridge()           # loop 未設定
    b.state("idle")               # 例外を出さない(no-op)
    b.mouth(0.3)
import aiohttp
import pytest


@pytest.mark.integration
async def test_real_ws_roundtrip():
    bridge = OverlayBridge(port=8771)
    await bridge.start()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect("http://127.0.0.1:8771/ws") as ws:
                # クライアント登録を待ってから配信
                import asyncio as _a
                await _a.sleep(0.05)
                await bridge._broadcast({"type": "state", "value": "thinking"})
                msg = await ws.receive(timeout=1.0)
                assert msg.data == '{"type": "state", "value": "thinking"}'
    finally:
        await bridge.stop()
