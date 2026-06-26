"""API 検索のディスパッチャ。

登録プロバイダを順に試し、最初にヒットした文脈文字列を返す。プロバイダは
async (text, *, session, config) -> str | None の契約。今は天気のみ。後で
他 API(乗換・ニュース等)を providers に足せる。
"""

from kotoha.tools.weather import weather_search

DEFAULT_PROVIDERS = (weather_search,)


async def api_search(text: str, *, session, config, providers=DEFAULT_PROVIDERS):
    """各プロバイダを順に試し、最初の非 None 結果を返す。無ければ None。"""
    for provider in providers:
        result = await provider(text, session=session, config=config)
        if result:
            return result
    return None
