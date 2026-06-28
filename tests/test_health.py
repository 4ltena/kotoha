import aiohttp
import pytest

from kotoha.config import Config
from kotoha.health import check_services, check_local_services, check_aux_endpoints


class _Resp:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _OkSession:
    def get(self, url):
        return _Resp(200)


class _BadSession:
    def get(self, url):
        raise RuntimeError("conn refused")


async def test_check_services_all_ok():
    res = await check_services(_OkSession(), ollama_url="http://o", tts_http_url="http://v")
    assert res == {"ollama": True, "tts_http": True}


async def test_check_services_marks_down_on_error():
    res = await check_services(_BadSession(), ollama_url="http://o", tts_http_url="http://v")
    assert res == {"ollama": False, "tts_http": False}


class _FakeResp:
    """aiohttp レスポンスの async context manager を模倣。

    error を渡すと __aenter__ で送出する(実 aiohttp は __aenter__ 中に
    ClientConnectorError を投げるため、try/except が async with を包む形を検証できる)。
    """

    def __init__(self, status=None, error=None):
        self._status = status
        self._error = error

    @property
    def status(self):
        return self._status

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, routes):
        # routes: list[(url_substring, _FakeResp)]
        self._routes = routes

    def get(self, url, **kwargs):
        for substr, resp in self._routes:
            if substr in url:
                return resp
        return _FakeResp(status=404)


async def test_check_local_services_all_ok():
    session = _FakeSession([
        ("/api/tags", _FakeResp(status=200)),
        ("9880", _FakeResp(status=200)),
    ])
    result = await check_local_services(
        session,
        ollama_url="http://localhost:11434",
        gptsovits_url="http://localhost:9880",
    )
    assert result == {"ollama": True, "gptsovits": True}


async def test_check_local_services_connection_error_both_down():
    err = aiohttp.ClientError()
    session = _FakeSession([
        ("/api/tags", _FakeResp(error=err)),
        ("9880", _FakeResp(error=err)),
    ])
    result = await check_local_services(
        session,
        ollama_url="http://localhost:11434",
        gptsovits_url="http://localhost:9880",
    )
    assert result == {"ollama": False, "gptsovits": False}


async def test_check_local_services_gptsovits_404_is_reachable():
    session = _FakeSession([
        ("/api/tags", _FakeResp(status=200)),
        ("9880", _FakeResp(status=404)),
    ])
    result = await check_local_services(
        session,
        ollama_url="http://localhost:11434",
        gptsovits_url="http://localhost:9880",
    )
    assert result == {"ollama": True, "gptsovits": True}


async def test_aux_endpoints_empty_when_perception_disabled():
    cfg = Config(screen_perception_enabled=False, vlm_perception_url="http://vii:1234")
    assert await check_aux_endpoints(_OkSession(), config=cfg) == {}


async def test_aux_endpoints_skip_when_same_as_ollama():
    # vlm/aux が空(=ollama_url にフォールバック)なら主チェック対象なので省く。
    cfg = Config(screen_perception_enabled=True, ollama_url="http://localhost:11434")
    assert await check_aux_endpoints(_OkSession(), config=cfg) == {}


async def test_aux_endpoints_probe_distinct_openai_vlm_and_ollama_aux():
    cfg = Config(
        screen_perception_enabled=True,
        ollama_url="http://localhost:11434",
        vlm_perception_url="http://vii:1234",
        vlm_perception_api="openai",
        aux_llm_url="http://vii:1234",
    )
    session = _FakeSession([
        ("/v1/models", _FakeResp(status=200)),   # 知覚VLM(openai)
        ("/api/tags", _FakeResp(status=200)),    # 補助LLM(ollama)
    ])
    result = await check_aux_endpoints(session, config=cfg)
    assert result == {"vlm": True, "aux": True}


async def test_aux_endpoints_marks_down_on_error():
    err = aiohttp.ClientError()
    cfg = Config(
        screen_perception_enabled=True,
        ollama_url="http://localhost:11434",
        vlm_perception_url="http://vii:1234",
        vlm_perception_api="ollama",
    )
    session = _FakeSession([("/api/tags", _FakeResp(error=err))])
    result = await check_aux_endpoints(session, config=cfg)
    assert result == {"vlm": False}
