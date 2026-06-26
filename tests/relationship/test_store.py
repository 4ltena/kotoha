from kotoha.relationship.store import RelationshipStore

DEF = {"affection": 90, "friendship": 90, "trust": 90, "respect": 90, "mood": 40}


def test_load_defaults_when_missing(tmp_path):
    s = RelationshipStore.load(str(tmp_path / "r.json"), defaults=DEF)
    assert (s.affection, s.friendship, s.trust, s.respect, s.mood) == (90, 90, 90, 90, 40)
    assert s.last_day == ""


def test_save_and_load_roundtrip(tmp_path):
    p = str(tmp_path / "r.json")
    s = RelationshipStore.load(p, defaults=DEF)
    s.affection = 85
    s.mood = -10
    s.last_day = "2026-06-27"
    s.save()
    s2 = RelationshipStore.load(p, defaults=DEF)
    assert s2.affection == 85 and s2.mood == -10 and s2.last_day == "2026-06-27"
    assert s2.friendship == 90


def test_load_corrupt_returns_defaults(tmp_path):
    p = tmp_path / "r.json"
    p.write_text("{ broken", encoding="utf-8")
    s = RelationshipStore.load(str(p), defaults=DEF)
    assert s.affection == 90 and s.mood == 40
