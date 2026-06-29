"""発話から操作意図を取り出す純ロジック。操作語が無ければ None で通常会話を素通しする。"""

import re
from dataclasses import dataclass

_DEMONSTRATIVES = ("ここ", "そこ", "あそこ", "これ", "それ", "あれ")
_CLICK_WORDS = ("クリック", "押して", "選んで", "タップ")
_DOUBLE_WORDS = ("ダブルクリック", "開いて", "ひらいて")
_QUOTED = re.compile(r"[「『](.+?)[」』]")

_NEG_WORDS = ("やめ", "いや", "ちがう", "違う", "だめ", "じゃない", "しないで", "やだ", "キャンセル")
_AFF_WORDS = ("うん", "はい", "いいよ", "おねがい", "お願い", "そう", "やって", "オーケー", "ok")


@dataclass(frozen=True)
class ActionRequest:
    kind: str
    target: str = ""
    text: str = ""
    keys: str = ""
    amount: int = 0


def _extract_target(prefix: str) -> str:
    t = prefix.strip().strip("、。 　")
    for p in ("を", "の", "に", "へ"):
        if t.endswith(p):
            t = t[:-1]
    t = t.strip()
    if not t or t in _DEMONSTRATIVES:
        return ""
    return t[:30]


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


def is_negative(text) -> bool:
    s = (text or "").strip().lower()
    return any(w in s for w in _NEG_WORDS)


def is_affirmative(text) -> bool:
    s = (text or "").strip().lower()
    if is_negative(s):
        return False
    return any(w in s for w in _AFF_WORDS)
