"""Holo2 グラウンディングクライアント。画像+指示→正規化座標→実OS座標へ写像する。

vlm_client の build_vlm_payload/parse_vlm_response を再利用する。Holo2 は
Qwen3-VL-8B-Thinking 由来で <think> を吐きうるので除去し、最終応答から座標を拾う。
失敗（接続不可・タイムアウト・パース不可）は None を返し例外を上げない（best-effort）。
"""

import logging
import re
from dataclasses import dataclass

import aiohttp

from kotoha.llm.vlm_client import build_vlm_payload, parse_vlm_response

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_NUM = r"(\d+(?:\.\d+)?)"
_PATTERNS = (
    re.compile(rf"click\(\s*{_NUM}\s*,\s*{_NUM}\s*\)", re.IGNORECASE),
    re.compile(rf"\(\s*{_NUM}\s*,\s*{_NUM}\s*\)"),
    re.compile(rf'"x"\s*:\s*{_NUM}.*?"y"\s*:\s*{_NUM}', re.DOTALL),
)

_DEFAULT_PROMPT = (
    "次の画面のスクリーンショットを見て、指示された UI 要素のクリック点を求めて。"
    "座標は画像に対して x, y それぞれ 0〜1000 で正規化した整数で 1 組だけ返す。"
)


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class GroundResult:
    x: int
    y: int
    raw: str


def parse_ground_response(text: str) -> "tuple[int, int] | None":
    """正規化座標 (nx, ny) を返す。<think> 除去→3段の正規表現→最初の一致のみ→範囲外は None。"""
    if not text:
        return None
    cleaned = _THINK_RE.sub("", text)
    for pat in _PATTERNS:
        m = pat.search(cleaned)
        if m:
            nx, ny = round(float(m.group(1))), round(float(m.group(2)))
            if 0 <= nx <= 1000 and 0 <= ny <= 1000:
                return (nx, ny)
            return None
    return None


def map_norm_to_abs(nx: int, ny: int, region: Region) -> "tuple[int, int]":
    """正規化 0〜1000 を region の実OS座標へ写像し、region 内へクランプする。"""
    if region.width <= 0 or region.height <= 0:
        return (region.left, region.top)
    x = region.left + round(nx / 1000 * region.width)
    y = region.top + round(ny / 1000 * region.height)
    x = max(region.left, min(region.left + region.width - 1, x))
    y = max(region.top, min(region.top + region.height - 1, y))
    return (x, y)


async def ground_target(
    image_b64: str,
    *,
    instruction: str,
    region: Region,
    model: str,
    base_url: str,
    api: str = "openai",
    session: "aiohttp.ClientSession | None" = None,
    timeout_s: float = 30.0,
    prompt: str = _DEFAULT_PROMPT,
) -> "GroundResult | None":
    """画像と指示を Holo2 へ送り GroundResult を返す。失敗は None（例外を上げない）。

    session=None のときは呼び出しごとに短命セッションを使い捨て、llama.cpp #17200
    （連続マルチモーダル要求の失敗）を回避する。
    """
    full_prompt = f"{prompt}\n対象: {instruction}"
    path, payload = build_vlm_payload(image_b64, prompt=full_prompt, model=model, api=api)
    own = session is None
    if own:
        session = aiohttp.ClientSession()
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s)
        async with session.post(f"{base_url}{path}", json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            obj = await resp.json()
        raw = parse_vlm_response(obj, api=api)
        norm = parse_ground_response(raw)
        if norm is None:
            return None
        x, y = map_norm_to_abs(norm[0], norm[1], region)
        return GroundResult(x=x, y=y, raw=raw)
    except Exception:
        logger.warning("grounding failed", exc_info=True)
        return None
    finally:
        if own:
            await session.close()
