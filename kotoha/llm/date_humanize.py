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


def format_time_spoken(now) -> str:
    """現在時刻を話し言葉の明確な形にする(モデルがそのまま答えられるよう)。"""
    wd = _WEEKDAYS[now.weekday()]
    return (
        f"今は{now.year}年{now.month}月{now.day}日({wd}) "
        f"{now.hour}時{now.minute:02d}分ごろ、{_time_band(now.hour)}です。"
    )


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
