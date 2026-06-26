from datetime import date

from kotoha.llm.date_humanize import humanize_dates

T = date(2026, 6, 27)   # 土曜


def test_relative_words():
    assert humanize_dates("2026-06-27", T) == "今日"
    assert humanize_dates("2026-06-28", T) == "明日"
    assert humanize_dates("2026-06-29", T) == "明後日"
    assert humanize_dates("2026-06-30", T) == "明々後日"


def test_strips_weekday_paren():
    assert humanize_dates("明日 2026-06-28（日）の天気", T) == "明日 明日の天気"
    assert humanize_dates("2026-06-28 (日)", T) == "明日"


def test_far_same_month_day_only():
    base = date(2026, 6, 1)
    assert humanize_dates("2026-06-20", base) == "20日"   # 同月・4日以上先 -> 日だけ


def test_cross_month_month_and_day():
    assert humanize_dates("2026-07-15", T) == "7月15日"   # 月をまたぐ -> 月+日
    assert humanize_dates("2026-07-01", T) == "7月1日"


def test_never_speaks_year():
    out = humanize_dates("予定は 2026-12-31 です", T)
    assert "2026" not in out and "12月31日" in out


def test_non_date_text_untouched():
    assert humanize_dates("バージョン 1-2-3 の話", T) == "バージョン 1-2-3 の話"
