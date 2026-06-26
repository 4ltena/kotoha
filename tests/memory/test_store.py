from kotoha.memory.store import MemoryStore


def test_save_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "memory.json")
    s = MemoryStore(p)
    s.long_term = "ユーザーは犬が好き"
    s.short_term = ["猫も好き"]
    s.raw_window = [{"role": "user", "content": "やあ"}]
    s.pending_raw = [{"role": "assistant", "content": "こんにちは"}]
    s.turns_since_compress = 3
    s.save()

    loaded = MemoryStore.load(p)
    assert loaded.long_term == "ユーザーは犬が好き"
    assert loaded.short_term == ["猫も好き"]
    assert loaded.raw_window == [{"role": "user", "content": "やあ"}]
    assert loaded.pending_raw == [{"role": "assistant", "content": "こんにちは"}]
    assert loaded.turns_since_compress == 3


def test_load_missing_file_returns_empty(tmp_path):
    s = MemoryStore.load(str(tmp_path / "nope.json"))
    assert s.long_term == ""
    assert s.short_term == []
    assert s.raw_window == []
    assert s.pending_raw == []
    assert s.turns_since_compress == 0


def test_load_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "memory.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = MemoryStore.load(str(p))
    assert s.long_term == ""
    assert s.short_term == []
