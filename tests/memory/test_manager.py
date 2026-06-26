import asyncio
from kotoha.config import Config
from kotoha.memory.store import MemoryStore
from kotoha.memory.manager import MemoryManager


def _cfg(tmp_path, **kw):
    return Config(
        memory_path=str(tmp_path / "m.json"),
        memory_keep_recent_turns=kw.get("W", 2),
        memory_compress_interval=kw.get("N", 2),
        memory_promote_threshold=kw.get("M", 3),
    )


def _manager(tmp_path, *, compress_fn, promote_fn=None, gemini=None, **kw):
    spawned = []

    def spawn(coro):
        spawned.append(coro)
        return coro

    async def _noop_promote(*a, **k):
        return "LT"

    mgr = MemoryManager(
        store=MemoryStore(str(tmp_path / "m.json")),
        config=_cfg(tmp_path, **kw),
        session=None,
        loop=asyncio.get_event_loop(),
        immutable_prompt="IMM",
        gemini_models=gemini,
        api_key=("k" if gemini else None),
        compress_fn=compress_fn,
        promote_fn=promote_fn or _noop_promote,
        spawn=spawn,
    )
    return mgr, spawned


async def test_build_messages_uses_immutable_and_window(tmp_path):
    async def cf(*a, **k):
        return []
    mgr, _ = _manager(tmp_path, compress_fn=cf)
    mgr.add_user("やあ")
    msgs = mgr.build_messages()
    assert msgs[0]["role"] == "system"
    assert "IMM" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "やあ"}


async def test_overflow_moves_to_pending_and_triggers_compress(tmp_path):
    seen = {}

    async def cf(turns, **k):
        seen["turns"] = list(turns)
        return ["要点1"]

    # W=2, N=2。3ターン入れると最古ターンが pending へ、N=2 到達で圧縮起動。
    mgr, spawned = _manager(tmp_path, compress_fn=cf, W=2, N=2)
    for i in range(3):
        mgr.add_user(f"u{i}")
        mgr.on_turn_end(f"a{i}")

    assert len(mgr.store.raw_window) == 4          # 直近2ターン=4メッセージ
    assert len(spawned) >= 1
    await asyncio.gather(*spawned)
    assert seen["turns"][0] == {"role": "user", "content": "u0"}   # 最古が圧縮対象
    assert mgr.store.short_term == ["要点1"]
    assert mgr.store.pending_raw == []
    assert mgr.store.turns_since_compress == 0


async def test_promotion_triggers_and_clears_snapshot(tmp_path):
    async def cf(turns, **k):
        return ["e1", "e2"]   # 1回の圧縮で2件

    async def pf(long_term, entries, **k):
        assert entries == ["e1", "e2"]
        return "新LT"

    # M=2。W=1,N=1 で毎ターン圧縮 -> すぐ閾値超え。
    mgr, spawned = _manager(tmp_path, compress_fn=cf, promote_fn=pf,
                            gemini=["m1"], W=1, N=1, M=2)
    mgr.add_user("u0"); mgr.on_turn_end("a0")
    mgr.add_user("u1"); mgr.on_turn_end("a1")
    # spawned には圧縮コルーチンが入る。順に await すると内部で昇格 spawn が積まれる。
    i = 0
    while i < len(spawned):
        await spawned[i]
        i += 1
    assert mgr.store.long_term == "新LT"
    assert mgr.store.short_term == []   # スナップショット分が除去


async def test_compress_failure_keeps_pending(tmp_path):
    async def cf(turns, **k):
        raise RuntimeError("4b down")

    mgr, spawned = _manager(tmp_path, compress_fn=cf, W=1, N=1)
    mgr.add_user("u0"); mgr.on_turn_end("a0")
    mgr.add_user("u1"); mgr.on_turn_end("a1")
    await asyncio.gather(*spawned)
    assert mgr.store.pending_raw != []      # 失敗時はバッチを捨てない
    assert mgr.store.short_term == []
