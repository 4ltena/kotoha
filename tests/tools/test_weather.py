from kotoha.config import Config
from kotoha.tools.weather import (
    is_weather_query,
    extract_city,
    format_weather,
    weather_search,
)


def test_is_weather_query():
    assert is_weather_query("今日の天気は？")
    assert is_weather_query("大阪の気温教えて")
    assert is_weather_query("weather in Tokyo")
    assert not is_weather_query("こんにちは、元気？")


def test_extract_city_known_and_default():
    assert extract_city("大阪の天気は？", "Tokyo") == "Osaka,JP"
    assert extract_city("天気は？", "Tokyo") == "Tokyo"          # 都市名なし -> 既定
    assert extract_city("沖縄の天気", "Tokyo") == "Naha,JP"


def test_format_weather():
    data = {
        "name": "Tokyo",
        "weather": [{"description": "晴れ"}],
        "main": {"temp": 22.4, "humidity": 60},
    }
    s = format_weather(data)
    assert "Tokyo" in s and "晴れ" in s and "22℃" in s and "60%" in s


async def test_weather_search_returns_context_on_query():
    captured = {}

    async def fake_fetch(city, *, api_key, session, units, lang, base_url="x"):
        captured["city"] = city
        captured["units"] = units
        return {"name": "Osaka", "weather": [{"description": "曇り"}],
                "main": {"temp": 18, "humidity": 70}}

    cfg = Config()
    out = await weather_search(
        "大阪の天気は？", session=None, config=cfg, api_key="k", fetch=fake_fetch
    )
    assert out is not None and "Osaka" in out and "曇り" in out
    assert captured["city"] == "Osaka,JP"
    assert captured["units"] == "metric"


async def test_weather_search_none_when_not_weather():
    async def fake_fetch(*a, **k):
        raise AssertionError("should not fetch")

    out = await weather_search(
        "こんにちは", session=None, config=Config(), api_key="k", fetch=fake_fetch
    )
    assert out is None


async def test_weather_search_none_without_key():
    async def fake_fetch(*a, **k):
        raise AssertionError("should not fetch")

    # api_key=None かつ環境変数も無い前提(テスト環境)。キー無しなら検索しない。
    import os
    os.environ.pop("OPENWEATHER_API_KEY", None)
    out = await weather_search(
        "天気は？", session=None, config=Config(), api_key=None, fetch=fake_fetch
    )
    assert out is None
