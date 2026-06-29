import base64
import io

import pytest

PIL = pytest.importorskip("PIL")
np = pytest.importorskip("numpy")
from PIL import Image  # noqa: E402

from kotoha.screen.capture import encode_frame, DxcamCapturer, MssCapturer  # noqa: E402


def test_encode_frame_downscales_and_is_valid_jpeg():
    src = Image.new("RGB", (2000, 1000), (10, 20, 30))
    b64 = encode_frame(src, max_long_edge=1024)
    assert isinstance(b64, str) and b64
    raw = base64.b64decode(b64)
    out = Image.open(io.BytesIO(raw))
    assert out.format == "JPEG"
    assert max(out.size) <= 1024
    assert out.size == (1024, 512)   # アスペクト比維持


def test_encode_frame_no_upscale_small_image():
    src = Image.new("RGB", (640, 480), (0, 0, 0))
    out = Image.open(io.BytesIO(base64.b64decode(encode_frame(src, max_long_edge=1024))))
    assert out.size == (640, 480)


def test_encode_frame_converts_non_rgb():
    src = Image.new("RGBA", (100, 100), (1, 2, 3, 255))
    out = Image.open(io.BytesIO(base64.b64decode(encode_frame(src))))
    assert out.mode == "RGB"


def test_dxcam_reemits_last_frame_when_grab_returns_none():
    cap = DxcamCapturer(max_long_edge=64)
    frames = [np.zeros((10, 10, 3), dtype=np.uint8), None, None]
    cap._grab = lambda: frames.pop(0)
    first = cap.capture()
    assert isinstance(first, str) and first        # 実フレーム
    assert cap.capture() == first                  # grab None -> 直近を再利用
    assert cap.capture() == first                  # 連続 None でも保つ


def test_dxcam_returns_none_before_any_frame():
    cap = DxcamCapturer()
    cap._grab = lambda: None
    assert cap.capture() is None                   # まだ一度も取れていなければ None


def test_capture_with_region_maps_monitor(monkeypatch):
    from kotoha.operate.grounding import Region

    cap = MssCapturer(max_long_edge=1024)

    class _Raw:
        size = (200, 100)
        rgb = b"\x00" * (200 * 100 * 3)

    class _Sct:
        monitors = [None, {"left": 10, "top": 20, "width": 200, "height": 100}]
        def grab(self, mon): return _Raw()

    cap._sct = _Sct()
    monkeypatch.setattr(cap, "_ensure", lambda: None)
    img_b64, region = cap.capture_with_region()
    assert isinstance(img_b64, str) and img_b64
    assert region == Region(left=10, top=20, width=200, height=100)
