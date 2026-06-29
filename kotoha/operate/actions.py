"""発話から操作意図を取り出す純ロジック。操作語が無ければ None で通常会話を素通しする。"""

import re
from dataclasses import dataclass

_DEMONSTRATIVES = ("ここ", "そこ", "あそこ", "これ", "それ", "あれ")
_CLICK_WORDS = ("クリック", "押して", "選んで", "タップ")
_DOUBLE_WORDS = ("ダブルクリック", "開いて", "ひらいて")
_QUOTED = re.compile(r"[「『](.+?)[」』]")

_DRAG_WORDS = ("ドラッグ", "移動", "動かし")

_NEG_WORDS = ("やめ", "いや", "ちがう", "違う", "だめ", "じゃない", "しないで", "やだ", "キャンセル")
_AFF_WORDS = ("うん", "はい", "いいよ", "おねがい", "お願い", "そう", "やって", "オーケー", "ok")


@dataclass(frozen=True)
class ActionRequest:
    kind: str
    target: str = ""
    text: str = ""
    keys: str = ""
    amount: int = 0
    to_target: str = ""


def _extract_target(prefix: str) -> str:
    t = prefix.strip().strip("、。 　")
    for p in ("を", "の", "に", "へ"):
        if t.endswith(p):
            t = t[:-1]
            break
    t = t.strip()
    if not t or t in _DEMONSTRATIVES:
        return ""
    return t[:30]


def _extract_drag(s: str) -> "tuple[str, str] | None":
    """「AをBに|へ <drag語>」から (A, B) を抽出。揃わなければ None。"""
    for w in _DRAG_WORDS:
        if w not in s:
            continue
        before = s.split(w)[0]
        if "を" not in before:
            return None
        a_part, rest = before.split("を", 1)
        # rest 末尾の に|へ より前を B とする
        to = ""
        for p in ("に", "へ"):
            if p in rest:
                to = rest.rsplit(p, 1)[0]
                break
        a = _extract_target(a_part + "を")   # _extract_target は末尾助詞を落とす
        b = _extract_target(to + "に") if to else ""
        if a and b:
            return a, b
        return None
    return None


def _extract_type_text(s: str) -> str:
    m = _QUOTED.search(s)
    if m:
        return m.group(1).strip()[:200]
    idx = s.find("と入力")
    if idx > 0:
        return s[:idx].strip()[:200]
    idx = s.find("入力")
    if idx > 0:
        return s[:idx].strip().rstrip("をに").strip()[:200]
    return ""


def parse_intent(text, *, config) -> "ActionRequest | None":
    s = text.strip()
    drag = _extract_drag(s)
    if drag is not None:
        return ActionRequest("drag", target=drag[0], to_target=drag[1])
    if "右クリック" in s:
        return ActionRequest("right_click", target=_extract_target(s.split("右クリック")[0]))
    if "スクロール" in s or "ページアップ" in s or "ページダウン" in s:
        up = ("上" in s) or ("ページアップ" in s)
        return ActionRequest("scroll", amount=5 if up else -5)
    for word, combo in config.hotkey_map:
        if word in s:
            return ActionRequest("hotkey", keys=combo)
    if "入力" in s:
        body = _extract_type_text(s)
        return ActionRequest("type", text=body) if body else None
    for w in _DOUBLE_WORDS:
        if w in s:
            return ActionRequest("double_click", target=_extract_target(s.split(w)[0]))
    for w in _CLICK_WORDS:
        if w in s:
            return ActionRequest("click", target=_extract_target(s.split(w)[0]))
    return None


_CONNECTORS = ("そして", "それから", "、")   # してから/てから は動詞活用と衝突するため除外


def parse_chain(text, *, config) -> "list[ActionRequest]":
    """発話を接続語で節に割って各節を parse_intent する。引用 「…」/『…』内の接続語は無視する。"""
    s = text.strip()
    # 引用範囲をプレースホルダへ退避してから分割する。
    spans = []

    def _mask(m):
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    masked = _QUOTED.sub(_mask, s)
    # 接続語で分割
    parts = [masked]
    for c in _CONNECTORS:
        parts = [p for seg in parts for p in seg.split(c)]

    def _restore(seg):
        for i, original in enumerate(spans):
            seg = seg.replace(f"\x00{i}\x00", original)
        return seg

    out = []
    for seg in parts:
        seg = _restore(seg).strip()
        if not seg:
            continue
        a = parse_intent(seg, config=config)
        if a is not None:
            out.append(a)
    if not out:
        # 接続語で何も取れない単一発話: 全体を1意図として解釈
        a = parse_intent(s, config=config)
        return [a] if a is not None else []
    return out


def is_negative(text) -> bool:
    s = (text or "").strip().lower()
    return any(w in s for w in _NEG_WORDS)


def is_affirmative(text) -> bool:
    s = (text or "").strip().lower()
    if is_negative(text):
        return False
    return any(w in s for w in _AFF_WORDS)
