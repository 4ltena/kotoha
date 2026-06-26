"""OpenWeather による現在天気の API 検索プロバイダ。

ユーザー発話が天気の質問なら、OpenWeather の現在天気を取得し、短い日本語の
文脈文字列にして返す。結果は LLM に「取得情報」として渡し、つくよみが自分の
口調で答える(RAG 的な API 検索)。API キーは環境変数 OPENWEATHER_API_KEY。
"""

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

OPENWEATHER_BASE = "https://api.openweathermap.org/data/2.5/weather"

# 天気質問の判定に使うキーワード(部分一致)。
_WEATHER_KEYWORDS = ("天気", "気温", "weather", "気候")

# 日本語の都市名 -> OpenWeather の q パラメータ(City,Country)。未知語は既定都市へ。
_CITY_MAP = {
    "東京": "Tokyo,JP",
    "大阪": "Osaka,JP",
    "名古屋": "Nagoya,JP",
    "札幌": "Sapporo,JP",
    "福岡": "Fukuoka,JP",
    "横浜": "Yokohama,JP",
    "京都": "Kyoto,JP",
    "神戸": "Kobe,JP",
    "仙台": "Sendai,JP",
    "広島": "Hiroshima,JP",
    "那覇": "Naha,JP",
    "沖縄": "Naha,JP",
}


def is_weather_query(text: str) -> bool:
    """発話が天気に関する質問か(キーワード部分一致)。"""
    low = text.lower()
    return any(k.lower() in low for k in _WEATHER_KEYWORDS)


def extract_city(text: str, default_city: str) -> str:
    """発話から都市を抽出。既知の日本語都市名があればそれを、無ければ既定都市。"""
    for jp, q in _CITY_MAP.items():
        if jp in text:
            return q
    return default_city


def format_weather(data: dict) -> str:
    """OpenWeather の現在天気 JSON を短い日本語文脈にする。"""
    name = data.get("name") or "指定地点"
    weather = (data.get("weather") or [{}])[0].get("description", "")
    main = data.get("main", {})
    temp = main.get("temp")
    humidity = main.get("humidity")
    s = f"{name}の現在の天気: {weather}".rstrip(": ")
    if temp is not None:
        s += f"、気温{round(temp)}℃"
    if humidity is not None:
        s += f"、湿度{humidity}%"
    return s + "。"


async def fetch_weather(
    city: str,
    *,
    api_key: str,
    session: aiohttp.ClientSession,
    units: str = "metric",
    lang: str = "ja",
    base_url: str = OPENWEATHER_BASE,
) -> dict:
    """OpenWeather 現在天気 API を呼び、JSON(dict)を返す。"""
    params = {"q": city, "appid": api_key, "units": units, "lang": lang}
    async with session.get(base_url, params=params) as resp:
        resp.raise_for_status()
        return await resp.json()


async def weather_search(
    text: str,
    *,
    session,
    config,
    api_key=None,
    fetch=fetch_weather,
) -> str | None:
    """天気質問なら現在天気の文脈文字列を返す。非該当/キー無し/失敗は None。"""
    key = api_key or os.environ.get("OPENWEATHER_API_KEY")
    if not key:
        return None
    if not is_weather_query(text):
        return None
    city = extract_city(text, config.openweather_default_city)
    try:
        data = await fetch(
            city,
            api_key=key,
            session=session,
            units=config.openweather_units,
            lang=config.openweather_lang,
        )
    except Exception:
        logger.warning("weather fetch failed (city=%s)", city)
        return None
    return format_weather(data)
