import asyncio
from datetime import datetime

from kotoha.config import Config
from kotoha.relationship.store import RelationshipStore
from kotoha.relationship.manager import RelationshipManager


def _mgr(tmp_path, *, analyze_fn, clock=None, affection=90, mood=40, analyze=True,
         r18_path=None, background_gate=None):
    spawned = []

    def spawn(coro):
        spawned.append(coro)
        return coro

    store = RelationshipStore(str(tmp_path / "r.json"), affection=affection, mood=mood)
    cfg = Config(
        relationship_path=str(tmp_path / "r.json"),
        relationship_analyze_enabled=analyze,
        relationship_r18_prompt_path=(r18_path or ""),   # 既定の実ファイルを読まないよう明示
    )
    mgr = RelationshipManager(
        store=store, config=cfg, session=None,
        loop=asyncio.get_event_loop(),
        analyze_fn=analyze_fn, spawn=spawn, clock=clock or datetime.now,
        background_gate=background_gate,
    )
    return mgr, spawned


async def test_on_turn_applies_deltas(tmp_path):
    async def af(user_text, store, *, model, session, base_url, context=None):
        return {"affection": 2, "mood": -1}

    mgr, spawned = _mgr(tmp_path, analyze_fn=af)
    mgr.on_turn("やあ")
    await asyncio.gather(*spawned)
    assert mgr.store.affection == 92 and mgr.store.mood == 39


async def test_on_turn_skips_analysis_when_disabled(tmp_path):
    async def af(*a, **k):
        return {"affection": 5}

    mgr, spawned = _mgr(tmp_path, analyze_fn=af, analyze=False)
    mgr.on_turn("やあ")
    assert spawned == []                 # 分析を起動しない(VRAM/速度優先)
    assert mgr.store.affection == 90      # 値は固定のまま


async def test_persona_context_and_r18_gate(tmp_path):
    async def af(*a, **k):
        return {}

    r18 = tmp_path / "r18.txt"
    r18.write_text("解禁テキスト", encoding="utf-8")

    high, _ = _mgr(tmp_path, analyze_fn=af, affection=90, r18_path=str(r18))
    ctx = high.persona_context()
    assert "親密度=90" in ctx
    assert high.r18_unlocked()
    assert "解禁テキスト" in ctx                       # 解禁時はファイル内容を注入

    low, _ = _mgr(tmp_path, analyze_fn=af, affection=50, r18_path=str(r18))
    assert not low.r18_unlocked()
    assert "解禁テキスト" not in low.persona_context()

    # ファイルが無ければ解禁でも何も足さない(公開既定で安全)
    nofile, _ = _mgr(
        tmp_path, analyze_fn=af, affection=90, r18_path=str(tmp_path / "none.txt")
    )
    assert "解禁テキスト" not in nofile.persona_context()


async def test_day_change_relaxes_mood(tmp_path):
    async def af(*a, **k):
        return {}

    mgr, spawned = _mgr(
        tmp_path, analyze_fn=af, mood=40,
        clock=lambda: datetime(2026, 6, 28, 10, 0),
    )
    mgr.store.last_day = "2026-06-27"      # 前日
    mgr.on_turn("おはよう")
    assert mgr.store.mood == 28            # int(40 * 0.7) 引きずりつつ減衰
    assert mgr.store.last_day == "2026-06-28"
    await asyncio.gather(*spawned)


async def test_gate_blocks_background_analyze(tmp_path):
    async def af(*a, **k):
        return {"affection": 5}

    mgr, spawned = _mgr(tmp_path, analyze_fn=af, background_gate=lambda: False)
    mgr.on_turn("hi")
    assert spawned == []                  # 省力ゲート中は起動しない
    assert mgr.store.affection == 90      # 値は固定のまま


async def test_gate_allows_background_analyze(tmp_path):
    async def af(*a, **k):
        return {}

    mgr, spawned = _mgr(tmp_path, analyze_fn=af, background_gate=lambda: True)
    mgr.on_turn("hi")
    assert len(spawned) == 1
    await asyncio.gather(*spawned)


async def test_no_gate_allows_by_default(tmp_path):
    async def af(*a, **k):
        return {}

    mgr, spawned = _mgr(tmp_path, analyze_fn=af, background_gate=None)
    mgr.on_turn("hi")
    assert len(spawned) == 1
    await asyncio.gather(*spawned)
