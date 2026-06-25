import aiohttp
import pytest

from kotoha.voice.tts_gptsovits import (
    DEFAULT_TTS_TIMEOUT,
    synthesize,
)

_FAKE_WAV = b"RIFF\x24\x00\x00\x00WAVEfake-pcm-bytes"


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status
        self.raised = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        self.raised = True
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=self.status
            )

    async def read(self) -> bytes:
        return self._body


class _FakeSession:
    """aiohttp.ClientSession 互換の最小フェイク。post() は同期で async ctx を返す。"""

    def __init__(self, body: bytes = _FAKE_WAV, status: int = 200):
        self._body = body
        self._status = status
        self.calls: list[dict] = []
        self.last_response: _FakeResponse | None = None

    def post(self, url, *, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        self.last_response = _FakeResponse(self._body, self._status)
        return self.last_response


async def test_synthesize_posts_to_tts_with_required_fields():
    sess = _FakeSession()
    out = await synthesize(
        "こんにちは",
        session=sess,
        ref_audio_path="/srv/ref.wav",
        prompt_text="参照の書き起こし",
    )

    assert out == _FAKE_WAV                      # await r.read() の戻り
    assert len(sess.calls) == 1
    call = sess.calls[0]
    assert call["url"] == "http://localhost:9880/tts"   # 既定 base_url + /tts に POST

    body = call["json"]
    assert body["text"] == "こんにちは"
    assert body["text_lang"] == "ja"
    assert body["ref_audio_path"] == "/srv/ref.wav"
    assert body["prompt_text"] == "参照の書き起こし"
    assert body["prompt_lang"] == "ja"
    assert body["media_type"] == "wav"
    assert body["streaming_mode"] is False
    assert body["speed_factor"] == 1.0

    # timeout が渡っていること（既定は DEFAULT_TTS_TIMEOUT）
    assert call["timeout"] is DEFAULT_TTS_TIMEOUT
    # raise_for_status() が read() の前に呼ばれていること
    assert sess.last_response.raised is True


async def test_synthesize_respects_overrides_and_base_url():
    sess = _FakeSession()
    custom_timeout = aiohttp.ClientTimeout(total=3.0)
    await synthesize(
        "テスト",
        session=sess,
        ref_audio_path="/srv/v2.wav",
        text_lang="en",
        prompt_lang="en",
        speed_factor=1.2,
        base_url="http://gpu-host:9881/",   # 末尾スラッシュは正規化される
        timeout=custom_timeout,
        extra={"top_k": 15, "temperature": 0.8},
    )

    call = sess.calls[0]
    assert call["url"] == "http://gpu-host:9881/tts"
    assert call["timeout"] is custom_timeout
    body = call["json"]
    assert body["text_lang"] == "en"
    assert body["prompt_lang"] == "en"
    assert body["speed_factor"] == 1.2
    assert body["top_k"] == 15            # extra がマージされる
    assert body["temperature"] == 0.8
    assert body["media_type"] == "wav"    # extra で消えない


async def test_synthesize_raises_on_http_error():
    sess = _FakeSession(status=400)
    with pytest.raises(aiohttp.ClientResponseError):
        await synthesize("x", session=sess, ref_audio_path="/srv/ref.wav")


def test_default_timeout_matches_config():
    assert isinstance(DEFAULT_TTS_TIMEOUT, aiohttp.ClientTimeout)
    assert DEFAULT_TTS_TIMEOUT.total == 15.0   # config.tts_timeout_s と一致


@pytest.mark.integration
async def test_synthesize_against_real_server():
    import os

    base_url = os.environ.get("GPTSOVITS_URL", "http://localhost:9880")
    ref = os.environ.get("GPTSOVITS_REF_AUDIO")
    if not ref:
        pytest.skip("GPTSOVITS_REF_AUDIO 未設定のためスキップ")
    async with aiohttp.ClientSession() as session:
        wav = await synthesize(
            "これは結合テストです。",
            session=session,
            ref_audio_path=ref,
            prompt_text=os.environ.get("GPTSOVITS_REF_TEXT", ""),
            base_url=base_url,
        )
    assert isinstance(wav, bytes)
    assert wav[:4] == b"RIFF"   # 自己記述 WAV
