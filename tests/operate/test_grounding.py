from kotoha.operate.grounding import (
    GroundResult, Region, ground_target, map_norm_to_abs, parse_ground_response,
)


def test_parse_strips_thinking_and_reads_click():
    text = "<think>左上のボタン…</think>\nclick(500, 250)"
    assert parse_ground_response(text) == (500, 250)


def test_parse_reads_bare_tuple_and_json_and_float():
    assert parse_ground_response("(120, 880)") == (120, 880)
    assert parse_ground_response('{"x": 10, "y": 20}') == (10, 20)
    assert parse_ground_response("click(512.6, 256.4)") == (513, 256)


def test_parse_rejects_out_of_range_and_missing():
    assert parse_ground_response("click(1200, 50)") is None
    assert parse_ground_response("見つかりません") is None
    assert parse_ground_response("") is None


def test_map_norm_to_abs_scales_and_clamps():
    r = Region(left=100, top=200, width=2000, height=1000)
    assert map_norm_to_abs(500, 500, r) == (1100, 700)
    assert map_norm_to_abs(1000, 1000, r) == (2099, 1199)   # 右下端へクランプ
    assert map_norm_to_abs(0, 0, Region(0, 0, 0, 0)) == (0, 0)   # ゼロ実寸ガード


async def test_ground_target_returns_mapped_result():
    class _Resp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def raise_for_status(self): pass
        async def json(self): return {"choices": [{"message": {"content": "click(500, 500)"}}]}

    class _Session:
        def post(self, url, **kw): return _Resp()

    r = await ground_target(
        "IMG", instruction="検索ボタン", region=Region(0, 0, 1000, 1000),
        model="holo2-8b", base_url="http://x", api="openai", session=_Session(),
    )
    assert isinstance(r, GroundResult) and (r.x, r.y) == (500, 500)
