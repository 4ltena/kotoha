"""会話から関係値の変化量(デルタ)をローカル LLM(4b)で見積もる。

ユーザーの発話・現在値・状況(天気等)から、各値の小さな変化量を JSON で得る。
よほどの発言が無い限り変化は小さく抑え、1ターンのデルタは上限でクランプする。
"""

import json
import logging
import re

from kotoha.llm.front_client import stream_chat
from kotoha.relationship.store import FIELDS

logger = logging.getLogger(__name__)

# 各値の許容範囲。
RANGES = {
    "affection": (0, 100),
    "friendship": (0, 100),
    "trust": (0, 100),
    "respect": (0, 100),
    "mood": (-50, 50),
}
DELTA_CLAMP = 5   # 1ターンの変化量の上限(暴走防止)

_SYSTEM = (
    "あなたはキャラ「つくよみ」とユーザーの関係値の変化を見積もる分析器。"
    "ユーザーの直近の発話・現在値・状況(天気等)から、各値の変化量だけを JSON で返す。"
    "よほどの発言(強い好意/暴言/信頼を損なう等)が無い限り、変化は ±0〜2 に抑える。"
    "affection/friendship/trust/respect は 0〜100、mood(その日の気分)は -50〜50。"
    "天気が良ければ mood を少し上げ、荒天なら少し下げてよい。"
    '出力は変化量のみの JSON 一つ。例: {"affection":1,"friendship":0,"trust":0,"respect":0,"mood":-1}'
)


def _coerce_int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def parse_deltas(text):
    """LLM 出力から最初の JSON を取り出し、既知キーの整数デルタ(クランプ済)にする。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    for k in FIELDS:
        if k in obj:
            out[k] = max(-DELTA_CLAMP, min(DELTA_CLAMP, _coerce_int(obj[k])))
    return out


def apply_deltas(store, deltas):
    """デルタを加算し、各値を範囲にクランプして store に反映する。"""
    for k, (lo, hi) in RANGES.items():
        if k in deltas:
            setattr(store, k, max(lo, min(hi, getattr(store, k) + deltas[k])))


def _format_state(store):
    return (f"affection={store.affection}, friendship={store.friendship}, "
            f"trust={store.trust}, respect={store.respect}, mood={store.mood}")


async def analyze(user_text, store, *, model, session, base_url,
                  context=None, llm_stream=stream_chat):
    """4b で関係値デルタを見積もり dict で返す。出力不正時は {}。"""
    user = f"現在値: {_format_state(store)}\n"
    if context:
        user += f"状況: {context}\n"
    user += f"ユーザーの発話: {user_text}"
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
    buf = ""
    async for piece in llm_stream(messages, model=model, base_url=base_url, session=session):
        buf += piece
    return parse_deltas(buf)
