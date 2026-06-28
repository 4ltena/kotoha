from datetime import date, datetime

from kotoha.llm.date_humanize import (
    humanize_dates,
    format_turn_context,
    format_time_for_speech,
    greeting_time_guidance,
    time_band,
)

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


def test_turn_context_includes_structured_time_band_and_place():
    now = datetime(2026, 6, 27, 19, 5)
    ctx = format_turn_context(now, place="Osaka,JP")
    assert "現在日付: 2026年6月27日(土)" in ctx
    assert "現在時刻: 夜の七時五分ごろ" in ctx
    assert "時間帯: 夜" in ctx
    assert "時刻を聞かれた時の返答" not in ctx
    assert "現在地: Osaka,JP" in ctx
    assert "19:05" not in ctx


def test_time_band_boundaries():
    assert time_band(datetime(2026, 6, 27, 4, 59)) == "深夜"
    assert time_band(datetime(2026, 6, 27, 5, 0)) == "朝"
    assert time_band(datetime(2026, 6, 27, 19, 0)) == "夜"


def test_greeting_guidance_prevents_morning_at_night():
    guidance = greeting_time_guidance("おはよう", datetime(2026, 6, 27, 19, 0))
    assert "現在の時間帯は「夜」" in guidance
    assert "もう朝ですよ" in guidance
    assert "今は夜ですよ" in guidance


def test_greeting_guidance_empty_when_morning_matches():
    assert greeting_time_guidance("おはよう", datetime(2026, 6, 27, 8, 0)) == ""


def test_time_for_speech_uses_12_hour_with_time_band():
    assert format_time_for_speech(datetime(2026, 6, 27, 19, 43)) == "今は夜の七時四十三分ごろです。"
    assert format_time_for_speech(datetime(2026, 6, 27, 8, 0)) == "今は朝の八時ごろです。"
