from kotoha.health import check_services


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
