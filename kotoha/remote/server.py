"""リモート音声サーバ。HTTPS/WSS(既定 5108)でブラウザ端末と音声を双方向にやり取りする。

- GET /        ブラウザ用クライアントページ
- GET /ws      音声 WebSocket
    client -> server  : バイナリ = Int16 mono 16kHz の PCM フレーム(マイク)
    server -> client  : バイナリ = 合成 WAV、テキスト(JSON) = 制御(例 {"type":"stop"})

接続中の1台を能動クライアントとして扱う。受信 PCM は on_audio で orchestrator へ流し、
合成音声は RemotePlayer 経由で送る。getUserMedia のため自己署名 HTTPS で待ち受ける。
"""

import logging
import os
import secrets
import ssl
from urllib.parse import urlparse

import numpy as np
from aiohttp import web

from kotoha.remote.cert import ensure_self_signed_cert
from kotoha.remote.player import RemotePlayer

logger = logging.getLogger(__name__)

_STATIC = os.path.join(os.path.dirname(__file__), "static")


def _local_ips():
    """証明書 SAN 用に 127.0.0.1 と既定経路の LAN IP を返す。"""
    import socket

    ips = ["127.0.0.1"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.append(ip)
    except Exception:
        pass
    return ips


class RemoteAudioServer:
    def __init__(self, *, config, loop, user_id: int = 0, token=None):
        self.config = config
        self._loop = loop
        self._user_id = user_id
        # 接続トークン(空なら自動生成)。LAN 公開のため認証で private 応答を保護する。
        self.token = token or secrets.token_urlsafe(16)
        self._ws = None            # 能動クライアント(同時1台のみ)
        self._on_audio = None
        self.player = RemotePlayer(
            loop=loop, send_audio=self._send_audio, send_control=self._send_control
        )
        self._runner = None
        self._cert_path = None

    def set_on_audio(self, on_audio) -> None:
        self._on_audio = on_audio

    # ---- 送信(RemotePlayer から) ----
    async def _send_audio(self, wav: bytes) -> None:
        ws = self._ws
        if ws is not None and not ws.closed:
            await ws.send_bytes(wav)

    async def _send_control(self, msg: dict) -> None:
        ws = self._ws
        if ws is not None and not ws.closed:
            await ws.send_json(msg)

    # ---- 受信 ----
    def _feed(self, data: bytes) -> None:
        if not self._on_audio or not data:
            return
        pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        self._on_audio(self._user_id, pcm)

    def _authorized(self, request) -> bool:
        t = request.query.get("t", "")
        if not secrets.compare_digest(t, self.token):
            return False
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return False   # cross-site WebSocket hijacking 対策(同一オリジンのみ)
        return True

    async def _ws_handler(self, request):
        if not self._authorized(request):
            return web.Response(status=401, text="unauthorized")
        if self._ws is not None and not self._ws.closed:
            return web.Response(status=409, text="busy")   # 同時接続は1台のみ(乗っ取り防止)
        ws = web.WebSocketResponse(max_msg_size=1 << 20)   # 1MiB 上限(メモリDoS対策)
        await ws.prepare(request)
        self._ws = ws
        logger.info("remote client connected: %s", request.remote)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.BINARY:
                    self._feed(msg.data)
                # TEXT(client 制御)は将来用。今は無視。
        finally:
            if self._ws is ws:
                self._ws = None
            logger.info("remote client disconnected")
        return ws

    async def _index(self, request):
        return web.FileResponse(os.path.join(_STATIC, "index.html"))

    async def _cert(self, request):
        # 端末に信頼登録するための公開証明書(秘密鍵は配らない)。
        # iOS は CA 証明書を DER(バイナリ)で受け取らないと invalid profile になるため、
        # PEM を DER へ変換して application/x-x509-ca-cert で返す。
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        with open(self._cert_path, "rb") as f:
            pem = f.read()
        der = x509.load_pem_x509_certificate(pem).public_bytes(serialization.Encoding.DER)
        return web.Response(
            body=der,
            headers={
                "Content-Type": "application/x-x509-ca-cert",
                "Content-Disposition": 'attachment; filename="kotoha-remote.cer"',
            },
        )

    async def _profile(self, request):
        # iOS 向けの構成プロファイル(.mobileconfig)に CA 証明書(DER->base64)を埋め込む。
        # 単体 .cer より確実にインストールできる(invalid profile 回避)。
        import base64
        import uuid

        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        with open(self._cert_path, "rb") as f:
            pem = f.read()
        der = x509.load_pem_x509_certificate(pem).public_bytes(serialization.Encoding.DER)
        b64 = base64.b64encode(der).decode()
        cert_uuid = str(uuid.uuid4())
        prof_uuid = str(uuid.uuid4())
        plist = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            "<key>PayloadContent</key><array><dict>\n"
            "<key>PayloadType</key><string>com.apple.security.root</string>\n"
            "<key>PayloadVersion</key><integer>1</integer>\n"
            "<key>PayloadIdentifier</key><string>net.kotoha.remote.ca</string>\n"
            f"<key>PayloadUUID</key><string>{cert_uuid}</string>\n"
            "<key>PayloadDisplayName</key><string>kotoha remote CA</string>\n"
            "<key>PayloadCertificateFileName</key><string>kotoha-remote.cer</string>\n"
            f"<key>PayloadContent</key><data>{b64}</data>\n"
            "</dict></array>\n"
            "<key>PayloadType</key><string>Configuration</string>\n"
            "<key>PayloadVersion</key><integer>1</integer>\n"
            "<key>PayloadIdentifier</key><string>net.kotoha.remote</string>\n"
            f"<key>PayloadUUID</key><string>{prof_uuid}</string>\n"
            "<key>PayloadDisplayName</key><string>kotoha remote</string>\n"
            "</dict></plist>"
        )
        return web.Response(
            body=plist.encode("utf-8"),
            headers={
                "Content-Type": "application/x-apple-aspen-config",
                "Content-Disposition": 'attachment; filename="kotoha-remote.mobileconfig"',
            },
        )

    async def start(self) -> None:
        cert_path, key_path = ensure_self_signed_cert(
            self.config.remote_audio_cert_dir, ip_addresses=_local_ips()
        )
        self._cert_path = cert_path
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_path, key_path)
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/cert.pem", self._cert)   # 端末への信頼登録用(DER)
        app.router.add_get("/profile.mobileconfig", self._profile)   # iOS 用構成プロファイル
        app.router.add_get("/ws", self._ws_handler)
        app.router.add_static("/static", _STATIC)   # vendor(three/three-vrm) と assets(VRM)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(
            self._runner,
            self.config.remote_audio_host,
            self.config.remote_audio_port,
            ssl_context=ssl_ctx,
        )
        await site.start()

    async def stop(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
