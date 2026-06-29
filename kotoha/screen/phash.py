"""difference hash(dhash)による画面の知覚的変化検出。純ロジック、PIL と numpy のみ。

完全一致では拾ってしまうカーソル点滅や時計更新のような微小変化を吸収し、
意味のある変化のときだけ再要約させるために使う。
"""

import base64
import io

import numpy as np


def dhash(image, hash_size: int = 8) -> int:
    """PIL.Image を difference hash(hash_size*hash_size ビット)の整数にする。"""
    img = image.convert("L").resize((hash_size + 1, hash_size))
    px = np.asarray(img, dtype=np.int16)
    diff = px[:, 1:] > px[:, :-1]   # 横方向の隣接画素の大小
    bits = 0
    for b in diff.flatten():
        bits = (bits << 1) | int(b)
    return bits


def hamming(a: int, b: int) -> int:
    """2つのハッシュのビット差。"""
    return bin(a ^ b).count("1")


def dhash_b64(image_b64: str, hash_size: int = 8) -> int:
    """base64 JPEG をデコードして dhash を返す。"""
    from PIL import Image   # 遅延 import
    raw = base64.b64decode(image_b64)
    img = Image.open(io.BytesIO(raw))
    return dhash(img, hash_size=hash_size)
