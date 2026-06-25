"""オーバーレイ(SP1)へ状態/口パクイベントを配信する WebSocket ブリッジ。

events シンク I/F(state/mouth)を実装し、接続中の各クライアントへ JSON を
ブロードキャストする。声ループを絶対にブロック・失敗させない(best-effort)。
state()/mouth() は任意スレッドから呼ばれうるため、loop.call_soon_threadsafe で
イベントループへマーシャリングする。
"""

import asyncio
import json
import logging
import time

from aiohttp import web

logger = logging.getLogger(__name__)


class OverlayBridge:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8770,
        loop=None,
        min_mouth_interval: float = 1.0 / 60.0,
        clock=None,
    ):
        self._host = host
        self._port = port
        self._loop = loop
        self._clients: set = set()
        self._runner = None
        self._min_mouth_interval = min_mouth_interval
        self._clock = clock or time.monotonic
        self._last_mouth = None

    # ---- events シンク(任意スレッドから安全) ----
    def state(self, value: str) -> None:
        self._submit({"type": "state", "value": value})

    def mouth(self, level: float) -> None:
        # spec §4.3: 口パクは ~60Hz 上限にスロットル(過剰なループ起床/送信を防ぐ)。
        now = self._clock()
        if self._last_mouth is not None and (now - self._last_mouth) < self._min_mouth_interval:
            return
        self._last_mouth = now
        self._submit({"type": "mouth", "value": float(level)})

    def _submit(self, message: dict) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._schedule, message)

    def _schedule(self, message: dict) -> None:
        asyncio.ensure_future(self._broadcast(message))

    # ---- 配信 ----
    async def _broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(message)
        for ws in list(self._clients):
            try:
                await ws.send_str(data)
            except Exception:
                self._clients.discard(ws)

    # ---- WS サーバ ----
    async def _handle_ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for _ in ws:
                pass   # SP1/SP2 はサーバ→クライアントの一方向。受信は無視。
        finally:
            self._clients.discard(ws)
        return ws

    async def start(self) -> None:
        self._loop = self._loop or asyncio.get_running_loop()
        app = web.Application()
        app.router.add_get("/ws", self._handle_ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("OverlayBridge listening on ws://%s:%s/ws", self._host, self._port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
