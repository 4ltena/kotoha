"""画面キャプチャ。縮小・エンコードは純関数、実キャプチャは遅延 import の薄い実装。

MssCapturer はクロスプラットフォーム(GDI)。DxcamCapturer は Windows の DXGI で
ゲーム画面も取得する。どちらも capture() は base64 JPEG か None を返す best-effort。
"""

import base64
import io
import logging

logger = logging.getLogger(__name__)


def encode_frame(image, *, max_long_edge: int = 1024, quality: int = 70) -> str:
    """PIL.Image を長辺 max_long_edge まで縮小し、JPEG base64(プレフィックス無し)にする。"""
    w, h = image.size
    long_edge = max(w, h)
    if long_edge > max_long_edge:
        scale = max_long_edge / long_edge
        image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))))
    if image.mode != "RGB":
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class MssCapturer:
    """mss(GDI) でプライマリモニタを取得する。"""

    def __init__(self, *, max_long_edge: int = 1024):
        self._max_long_edge = max_long_edge
        self._sct = None

    def _ensure(self):
        if self._sct is None:
            import mss   # 遅延 import
            self._sct = mss.mss()

    def capture(self) -> str | None:
        try:
            from PIL import Image   # 遅延 import
            self._ensure()
            mon = self._sct.monitors[1]   # [0]=全体, [1]=プライマリ
            raw = self._sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
            return encode_frame(img, max_long_edge=self._max_long_edge)
        except Exception:
            logger.warning("mss capture failed", exc_info=True)
            return None

    def close(self) -> None:
        """GDI コンテキストを解放する。未生成なら何もしない。"""
        sct = self._sct
        self._sct = None
        if sct is not None:
            try:
                sct.close()
            except Exception:
                logger.warning("mss close failed", exc_info=True)


class DxcamCapturer:
    """dxcam(DXGI Desktop Duplication) でゲーム画面も取得する(Windows)。"""

    def __init__(self, *, max_long_edge: int = 1024):
        self._max_long_edge = max_long_edge
        self._cam = None

    def _ensure(self):
        if self._cam is None:
            import dxcam   # 遅延 import (dxcam-cpp も import 名は dxcam)
            self._cam = dxcam.create(output_color="RGB")

    def capture(self) -> str | None:
        try:
            from PIL import Image   # 遅延 import
            self._ensure()
            frame = self._cam.grab()   # 新フレームが無ければ None
            if frame is None:
                return None
            img = Image.fromarray(frame)   # H×W×3 RGB ndarray
            return encode_frame(img, max_long_edge=self._max_long_edge)
        except Exception:
            logger.warning("dxcam capture failed", exc_info=True)
            return None

    def close(self) -> None:
        """DXGI 複製オブジェクトを解放する。未生成なら何もしない。"""
        cam = self._cam
        self._cam = None
        if cam is None:
            return
        for name in ("release", "stop"):   # dxcam-cpp のAPI差を吸収
            fn = getattr(cam, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    logger.warning("dxcam %s failed", name, exc_info=True)
