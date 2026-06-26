import asyncio
import functools
import logging
import os

import aiohttp

from kotoha.config import Config
from kotoha.health import check_local_services
from kotoha.memory import MemoryStore, MemoryManager
from kotoha.memory.discovery import discover_gemini_models
from kotoha.events import NullEvents
from kotoha.overlay_bridge import OverlayBridge
from kotoha.llm.front_client import stream_chat
from kotoha.orchestrator import Orchestrator, make_on_audio
from kotoha.voice.mic import MicCapture
from kotoha.voice.speaker import LocalSpeaker
from kotoha.voice.stt import Transcriber, build_whisper
from kotoha.voice.tts_gptsovits import synthesize
from kotoha.voice.vad import SileroVad

logger = logging.getLogger(__name__)


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
    memory=None,
):
    """設定と長命セッションから Orchestrator を結線する(単体テスト可能)。

    transcriber / player を注入しなければ、それぞれ実装(whisper / LocalSpeaker)を生成する。
    """
    if transcriber is None:
        # build_whisper は生の WhisperModel を返す。.transcribe が文字列を返すよう
        # Transcriber で包む(生 model の .transcribe は (segments, info) タプル)。
        model = build_whisper(
            config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
        transcriber = Transcriber(model)
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
        memory=memory,
    )


def _print_audio_devices(config) -> None:
    """選択されている入出力デバイスを表示する(デバッグ用)。"""
    try:
        import sounddevice as sd

        devs = sd.query_devices()
        default_in, default_out = sd.default.device
        in_idx = config.input_device if config.input_device is not None else default_in
        out_idx = config.output_device if config.output_device is not None else default_out

        def _name(idx):
            try:
                return devs[int(idx)]["name"]
            except Exception:
                return str(idx)

        print(f"[audio] input (mic): {_name(in_idx)} (index={in_idx})")
        print(f"[audio] output (speaker): {_name(out_idx)} (index={out_idx})")
    except Exception as e:
        print(f"[audio] failed to query devices: {e}")


async def run_local(config: Config) -> None:
    """ローカル(マイク+スピーカ)で会話ループを常駐させる。integration 専用。"""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
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
            raise RuntimeError(f"required services unreachable: {status}")

        bridge = None
        events = NullEvents()
        on_amplitude = None
        if config.overlay_enabled:
            bridge = OverlayBridge(
                host=config.overlay_ws_host, port=config.overlay_ws_port, loop=loop
            )
            try:
                await bridge.start()
                events = bridge
                on_amplitude = bridge.mouth
                print(
                    f"[overlay] WS server: "
                    f"ws://{config.overlay_ws_host}:{config.overlay_ws_port}/ws"
                )
            except Exception:
                logger.exception("overlay bridge failed to start; continuing without overlay")
                bridge = None   # events は NullEvents()、on_amplitude は None のまま

        memory = None
        if config.memory_enabled:
            store = MemoryStore.load(config.memory_path)
            api_key = os.environ.get("GEMINI_API_KEY")
            model_chain: list[str] = []
            if api_key:
                try:
                    model_chain = await discover_gemini_models(
                        api_key,
                        priority=config.memory_gemini_model_priority,
                        session=session,
                    )
                    print(f"[memory] gemini models: {model_chain}")
                except Exception:
                    logger.warning("gemini model discovery failed; promotion disabled")
            memory = MemoryManager(
                store=store,
                config=config,
                session=session,
                loop=loop,
                gemini_models=model_chain,
                api_key=api_key,
            )
            print(f"[memory] enabled (store={config.memory_path})")
        orch = build_orchestrator(
            config,
            session=session,
            loop=loop,
            events=events,
            on_amplitude=on_amplitude,
            memory=memory,
        )
        # TTS ウォームアップ: 初回合成が払うモデル/参照キャッシュ確立コスト(数秒)を
        # 会話開始前に消化し、最初の応答の遅延を無くす。合成結果は再生せず捨てる。
        try:
            import time

            t0 = time.perf_counter()
            print("Warming up TTS...")
            await asyncio.wait_for(
                orch.tts("ウォームアップ。"), timeout=config.tts_timeout_s
            )
            print(f"TTS warm-up done ({time.perf_counter() - t0:.2f}s)")
        except Exception:
            logger.warning("TTS warm-up failed; continuing")

        mic = MicCapture(
            make_on_audio(orch),
            user_id=config.local_user_id,
            device=config.input_device,
        )
        mic.start()
        _print_audio_devices(config)
        print("Mic capture started. Speak now. Ctrl+C to quit.")
        try:
            await asyncio.Event().wait()   # KeyboardInterrupt まで常駐
        finally:
            mic.stop()
            if memory is not None:
                await memory.aclose()
            if bridge is not None:
                await bridge.stop()


def main() -> None:
    try:
        asyncio.run(run_local(Config()))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
