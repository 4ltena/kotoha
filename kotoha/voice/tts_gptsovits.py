"""GPT-SoVITS api_v2.py (既定ポート 9880) の薄い非同期 TTS クライアント。

POST {base_url}/tts に JSON を送り、media_type="wav" / streaming_mode=False で
1文ぶんの完結した自己記述 WAV バイト列を取得する。サーバ側で重み(GPT/SoVITS)は
起動時に読み込まれている前提で、本クライアントは重み管理を一切行わない。

オーケストレータは functools.partial(synthesize, session=..., ref_audio_path=...,
prompt_text=...) を tts として注入し、async (text: str) -> bytes 契約を得る。
"""

import aiohttp

# config.tts_timeout_s = 15.0 と一致させる。
DEFAULT_TTS_TIMEOUT = aiohttp.ClientTimeout(total=15.0)


async def synthesize(
    text: str,
    *,
    session: aiohttp.ClientSession,
    ref_audio_path: str,
    prompt_text: str = "",
    text_lang: str = "ja",
    prompt_lang: str = "ja",
    speed_factor: float = 1.0,
    base_url: str = "http://localhost:9880",
    timeout: aiohttp.ClientTimeout = DEFAULT_TTS_TIMEOUT,
    extra: dict | None = None,
) -> bytes:
    """text を 1 リクエストで合成し、完結した WAV バイト列を返す。

    ref_audio_path は GPT-SoVITS サーバホスト上の参照音声へのパス。
    extra で top_k / temperature 等の追加パラメータを上書き/追加できる。
    """
    payload: dict = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "speed_factor": speed_factor,
        "media_type": "wav",
        "streaming_mode": False,
    }
    if extra:
        payload.update(extra)

    url = base_url.rstrip("/") + "/tts"
    async with session.post(url, json=payload, timeout=timeout) as resp:
        resp.raise_for_status()
        return await resp.read()


async def synthesize_default(
    text: str,
    *,
    ref_audio_path: str,
    **kwargs,
) -> bytes:
    """自前で ClientSession を開いて synthesize に委譲する（統合/手動実行用）。

    アプリ本体は通常、共有 session を注入した synthesize を使うこと。
    """
    async with aiohttp.ClientSession() as session:
        return await synthesize(
            text,
            session=session,
            ref_audio_path=ref_audio_path,
            **kwargs,
        )
