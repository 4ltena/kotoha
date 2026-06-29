import aiohttp

from kotoha.diagnostics import (
    diagnose,
    diagnose_screen,
    format_report,
    list_ollama_models,
    model_present,
)


class _Resp:
    def __init__(self, status=200, json_data=None, error=None):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._json


class _RouteSession:
    """URL 部分一致で _Resp を返す最小 fake。"""

    def __init__(self, routes):
        self._routes = routes  # list[(substr, _Resp)]

    def get(self, url, **kwargs):
        for substr, resp in self._routes:
            if substr in url:
                return resp
        return _Resp(status=404)


_TAGS = {"models": [{"name": "qwen3.5:4b"}, {"name": "llama3.2:latest"}]}


async def test_list_ollama_models_returns_names():
    sess = _RouteSession([("/api/tags", _Resp(200, _TAGS))])
    names = await list_ollama_models(sess, ollama_url="http://localhost:11434")
    assert names == ["qwen3.5:4b", "llama3.2:latest"]


async def test_list_ollama_models_empty_on_connection_error():
    sess = _RouteSession([("/api/tags", _Resp(error=aiohttp.ClientError()))])
    names = await list_ollama_models(sess, ollama_url="http://localhost:11434")
    assert names == []


def test_model_present_exact_match():
    assert model_present(["qwen3.5:4b", "llama3.2:latest"], "qwen3.5:4b") is True


def test_model_present_family_match_when_no_tag():
    assert model_present(["qwen3.5:4b"], "qwen3.5") is True


def test_model_present_missing():
    assert model_present(["llama3.2:latest"], "qwen3.5:4b") is False


async def test_diagnose_aggregates_services_and_model(monkeypatch):
    from kotoha.config import Config

    cfg = Config(
        ollama_url="http://localhost:11434",
        gptsovits_url="http://localhost:9880",
        ollama_model="qwen3.5:4b",
    )
    sess = _RouteSession([
        ("/api/tags", _Resp(200, _TAGS)),
        ("9880", _Resp(200)),
    ])
    result = await diagnose(cfg, session=sess)
    assert result["ollama"] is True
    assert result["gptsovits"] is True
    assert result["model"] == "qwen3.5:4b"
    assert result["model_present"] is True
    assert "qwen3.5:4b" in result["models"]


def test_format_report_all_ok_present():
    report = format_report({
        "ollama": True, "gptsovits": True,
        "model": "qwen3.5:4b", "model_present": True, "models": [],
    })
    assert "OK" in report
    assert "present" in report
    assert "MISSING" not in report


def test_format_report_model_missing_shows_pull_hint():
    report = format_report({
        "ollama": True, "gptsovits": False,
        "model": "qwen3.5:4b", "model_present": False, "models": [],
    })
    assert "MISSING" in report
    assert "ollama pull qwen3.5:4b" in report
    assert "DOWN" in report


# ---------------------------------------------------------------------------
# diagnose_screen tests
# ---------------------------------------------------------------------------

from kotoha.config import Config  # noqa: E402


class _OkSession:
    def get(self, url, **kwargs):
        return _Resp(200)


async def test_diagnose_screen_none_when_disabled():
    cfg = Config(screen_perception_enabled=False)
    assert await diagnose_screen(cfg, session=_OkSession()) is None


async def test_diagnose_screen_reports_vlm_and_capture():
    cfg = Config(
        screen_perception_enabled=True,
        ollama_url="http://localhost:11434",
        vlm_perception_api="ollama",
    )
    result = await diagnose_screen(
        cfg, session=_OkSession(), capture_probe=lambda: "IMGB64",
    )
    assert result["vlm_ok"] is True
    assert result["capture_ok"] is True


async def test_diagnose_screen_capture_failure_is_caught():
    cfg = Config(screen_perception_enabled=True, vlm_perception_api="ollama")

    def boom():
        raise RuntimeError("no display")

    result = await diagnose_screen(cfg, session=_OkSession(), capture_probe=boom)
    assert result["capture_ok"] is False
