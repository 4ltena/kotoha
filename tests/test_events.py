from kotoha.events import NullEvents


def test_null_events_state_and_mouth_are_noops():
    ev = NullEvents()
    assert ev.state("speaking") is None
    assert ev.mouth(0.5) is None
