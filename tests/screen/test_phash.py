import base64
import io

from PIL import Image

from kotoha.screen.phash import dhash, dhash_b64, hamming


def _img(color):
    return Image.new("RGB", (64, 64), color)


def _b64(image):
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_identical_images_have_zero_distance():
    a = dhash(_img((120, 120, 120)))
    b = dhash(_img((120, 120, 120)))
    assert hamming(a, b) == 0


def test_very_different_images_have_large_distance():
    # 左右半分で白黒に分けた画像 vs 一様灰色。dhash は構造差を拾う。
    split = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(32, 64):
        for y in range(64):
            split.putpixel((x, y), (255, 255, 255))
    assert hamming(dhash(split), dhash(_img((120, 120, 120)))) >= 8


def test_dhash_b64_matches_dhash_of_decoded():
    img = _img((30, 200, 90))
    assert hamming(dhash_b64(_b64(img)), dhash(img)) <= 2   # JPEG 量子化の許容


def test_hash_is_64_bit_for_default_size():
    assert 0 <= dhash(_img((10, 20, 30))) < (1 << 64)
