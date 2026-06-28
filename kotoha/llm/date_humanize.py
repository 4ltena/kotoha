"""応答テキスト中の ISO 形式の日付を会話的な表現へ変換する。

「2026-06-28（日）」のような形式は音声向きでないため、今日/明日/明後日/明々後日、
それ以降は同月なら「28日」、月をまたぐなら「6月28日」に直す。西暦・曜日は出さない。
"""

import re
from datetime import date

# YYYY-M-D と、続く任意の曜日括弧「(日)」「（日）」をまとめて捕捉。
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s*[（(][^）)]*[）)])?")
_REL = {0: "今日", 1: "明日", 2: "明後日", 3: "明々後日"}

_WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")
_KANJI_DIGITS = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九")


def _kanji_number(n: int) -> str:
    if 0 <= n < 10:
        return _KANJI_DIGITS[n]
    if n < 20:
        return "十" + ("" if n == 10 else _KANJI_DIGITS[n - 10])
    tens, ones = divmod(n, 10)
    return _KANJI_DIGITS[tens] + "十" + ("" if ones == 0 else _KANJI_DIGITS[ones])


def _time_band(hour: int) -> str:
    if 5 <= hour < 11:
        return "朝"
    if 11 <= hour < 17:
        return "昼"
    if 17 <= hour < 19:
        return "夕方"
    if 19 <= hour < 24:
        return "夜"
    return "深夜"


def time_band(now) -> str:
    """datetime から会話用の時間帯を返す。"""
    return _time_band(now.hour)


def _hour_for_speech(hour: int) -> str:
    if hour == 0:
        return "深夜零時"
    if 1 <= hour <= 4:
        return f"深夜{_kanji_number(hour)}時"
    if 5 <= hour <= 10:
        return f"朝の{_kanji_number(hour)}時"
    if 11 <= hour <= 16:
        return f"昼の{_kanji_number(hour)}時"
    if 17 <= hour <= 18:
        return f"夕方の{_kanji_number(hour)}時"
    if 19 <= hour <= 23:
        return f"夜の{_kanji_number(hour - 12)}時"
    return f"{_kanji_number(hour)}時"


def format_time_for_speech(now) -> str:
    """時刻を声に出しやすい話し言葉へ整える。"""
    if now.minute == 0:
        return f"今は{_hour_for_speech(now.hour)}ごろです。"
    return f"今は{_hour_for_speech(now.hour)}{_kanji_number(now.minute)}分ごろです。"


def format_time_context_value(now) -> str:
    """現在状況に入れる、返答文ではない時刻表現。"""
    return format_time_for_speech(now).removeprefix("今は").removesuffix("です。")


def format_turn_context(now, *, place: str = "") -> str:
    """毎ターン注入する、時刻・時間帯・地点の構造化コンテキスト。"""
    wd = _WEEKDAYS[now.weekday()]
    lines = [
        f"現在日付: {now.year}年{now.month}月{now.day}日({wd})",
        f"現在時刻: {format_time_context_value(now)}",
        f"時間帯: {time_band(now)}",
    ]
    if place.strip():
        lines.append(f"現在地: {place.strip()}")
    lines.append("時刻・日付・挨拶・場所の判断では、この現在の状況を参考にする。")
    lines.append("時刻は、ユーザーが時刻を聞いた時だけ会話文として使う。")
    return "\n".join(lines)


def greeting_time_guidance(text: str, now) -> str:
    """時間帯に合わない挨拶だけ、ターン専用の明示指示を返す。"""
    band = time_band(now)
    if "おはよう" in text or "お早う" in text:
        if band != "朝":
            return (
                "ユーザーは朝の挨拶「おはよう」と言ったが、現在の時間帯は"
                f"「{band}」。返答では「もう朝ですよ」とは言わない。"
                f"「今は{band}ですよ」のように現在の時間帯を使い、短く理由を尋ねる。"
            )
    if "おやすみ" in text or "お休み" in text:
        if band in ("朝", "昼"):
            return (
                "ユーザーは寝る前の挨拶「おやすみ」と言ったが、現在の時間帯は"
                f"「{band}」。返答では現在の時間帯を使い、短く理由を尋ねる。"
            )
    return ""


def humanize_dates(text: str, today: date) -> str:
    """text 中の ISO 日付を会話的表現に置換して返す。"""

    def repl(mo: "re.Match") -> str:
        try:
            target = date(int(mo.group(1)), int(mo.group(2)), int(mo.group(3)))
        except ValueError:
            return mo.group(0)   # 不正な日付はそのまま
        diff = (target - today).days
        if diff in _REL:
            return _REL[diff]
        if (target.year, target.month) == (today.year, today.month):
            return f"{target.day}日"          # 同月でより先 -> 日だけ
        return f"{target.month}月{target.day}日"  # 月をまたぐ -> 月+日

    return _ISO_DATE_RE.sub(repl, text)
