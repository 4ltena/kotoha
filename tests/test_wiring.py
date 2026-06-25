from kotoha.orchestrator import make_on_audio


def test_make_on_audio_forwards_to_feed_audio():
    calls = []

    class _O:
        def feed_audio(self, uid, audio):
            calls.append((uid, audio))

    on_audio = make_on_audio(_O())
    on_audio(5, "AUDIO")
    assert calls == [(5, "AUDIO")]
