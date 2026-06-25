import aiohttp
import pytest

from kotoha.health import check_services, check_local_services


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
