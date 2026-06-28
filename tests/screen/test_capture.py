import base64
import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from kotoha.screen.capture import encode_frame  # noqa: E402


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
