import asyncio
import functools

import aiohttp

from kotoha.config import Config
from kotoha.health import check_local_services
from kotoha.events import NullEvents
from kotoha.overlay_bridge import OverlayBridge
from kotoha.llm.front_client import stream_chat
from kotoha.orchestrator import Orchestrator, make_on_audio
from kotoha.voice.mic import MicCapture
from kotoha.voice.speaker import LocalSpeaker
from kotoha.voice.stt import build_whisper
from kotoha.voice.tts_gptsovits import synthesize
from kotoha.voice.vad import SileroVad


def build_orchestrator(
    config,
    *,
    session,
    loop,
    transcriber=None,
    player=None,
    vad_factory=SileroVad,
    events=NullEvents(),
    on_amplitude=None,
):
    """設定と長命セッションから Orchestrator を結線する(単体テスト可能)。

    transcriber / player を注入しなければ、それぞれ実装(whisper / LocalSpeaker)を生成する。
    """
    if transcriber is None:
        transcriber = build_whisper(
            config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
    if player is None:
        player = LocalSpeaker(loop=loop, on_amplitude=on_amplitude)

    tts = functools.partial(
        synthesize,
        session=session,
        base_url=config.gptsovits_url,
        ref_audio_path=config.gptsovits_ref_audio_path,
        prompt_text=config.gptsovits_prompt_text,
        text_lang=config.gptsovits_text_lang,
        prompt_lang=config.gptsovits_prompt_lang,
        speed_factor=config.gptsovits_speed_factor,
        # HTTP 層のタイムアウトも config に合わせる(既定 15s を上書き)。
        timeout=aiohttp.ClientTimeout(total=config.tts_timeout_s),
    )
    llm_stream = functools.partial(
        stream_chat,
        base_url=config.ollama_url,
        session=session,
    )

    # フェーズ1 bot.py と同一の明示 kwargs 配線。Orchestrator の署名は変更しない。
    return Orchestrator(
        transcriber=transcriber,
        llm_stream=llm_stream,
        tts=tts,
        player=player,
        model=config.ollama_model,
        vad_factory=vad_factory,
        history_max_turns=config.history_max_turns,
        vad_threshold=config.vad_threshold,
        vad_silence_ms=config.vad_silence_ms,
        bargein_trigger_ms=config.bargein_trigger_ms,
        fallback_text=config.fallback_text,
        stt_timeout=config.stt_timeout_s,
        tts_timeout=config.tts_timeout_s,
        play_timeout=config.play_timeout_s,
        loop=loop,
        events=events,
    )


async def run_local(config: Config) -> None:
    """ローカル(マイク+スピーカ)で会話ループを常駐させる。integration 専用。"""
    loop = asyncio.get_running_loop()
    timeout = aiohttp.ClientTimeout(total=None, sock_read=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        status = await check_local_services(
            session,
            ollama_url=config.ollama_url,
            gptsovits_url=config.gptsovits_url,
        )
        for name, ok in status.items():
            print(f"[health] {name}: {'OK' if ok else 'DOWN'}")
        if not all(status.values()):
            raise RuntimeError(f"必要なサービスに接続できません: {status}")

        bridge = None
        events = NullEvents()
        on_amplitude = None
        if config.overlay_enabled:
            bridge = OverlayBridge(
                host=config.overlay_ws_host, port=config.overlay_ws_port, loop=loop
            )
            await bridge.start()
            events = bridge
            on_amplitude = bridge.mouth
            print(
                f"[overlay] WS サーバ起動: "
                f"ws://{config.overlay_ws_host}:{config.overlay_ws_port}/ws"
            )

        orch = build_orchestrator(
            config,
            session=session,
            loop=loop,
            events=events,
            on_amplitude=on_amplitude,
        )
        mic = MicCapture(
            make_on_audio(orch),
            user_id=config.local_user_id,
            device=config.input_device,
        )
        mic.start()
        print("マイク入力を開始しました。Ctrl+C で終了します。")
        try:
            await asyncio.Event().wait()   # KeyboardInterrupt まで常駐
        finally:
            mic.stop()
            if bridge is not None:
                await bridge.stop()


def main() -> None:
    try:
        asyncio.run(run_local(Config()))
    except KeyboardInterrupt:
        print("\n終了します。")


if __name__ == "__main__":
    main()
