import asyncio
import contextlib
import functools
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from kotoha.config import Config, build_config
from kotoha.health import check_local_services, check_aux_endpoints
from kotoha.memory import MemoryStore, MemoryManager
from kotoha.memory.discovery import discover_gemini_models
from kotoha.events import NullEvents
from kotoha.overlay_bridge import OverlayBridge
from kotoha.llm.front_client import stream_chat
from kotoha.llm.vlm_client import vlm_describe
from kotoha.orchestrator import Orchestrator, make_on_audio
from kotoha.screen.capture import DxcamCapturer, MssCapturer
from kotoha.screen.detector import GameModeLoop
from kotoha.screen.perceiver import ScreenPerceiver
from kotoha.screen.state import ScreenContext
from kotoha.tools.registry import api_search as _api_search
from kotoha.relationship import RelationshipStore, RelationshipManager
from kotoha.voice.mic import MicCapture
from kotoha.voice.speaker import LocalSpeaker
from kotoha.voice.stt import Transcriber, build_whisper
from kotoha.voice.tts_gptsovits import synthesize
from kotoha.voice.vad import SileroVad

logger = logging.getLogger(__name__)


def _display_place(config) -> str:
    """毎ターンの地点文脈に入れる表示名。"""
    return (
        config.local_place
        or os.environ.get("KOTOHA_PLACE")
        or os.environ.get("OPENWEATHER_CITY")
        or config.openweather_default_city
    )


def _clock_for_config(config):
    """設定タイムゾーンで現在時刻を返す clock。"""
    try:
        tz = ZoneInfo(config.local_timezone)
    except ZoneInfoNotFoundError:
        if config.local_timezone == "Asia/Tokyo":
            tz = timezone(timedelta(hours=9), "JST")
        else:
            logger.warning("unknown timezone %s; using system local time", config.local_timezone)
            return datetime.now

    def _clock():
        return datetime.now(tz)

    return _clock


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
    relationship=None,
    screen_context=None,
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
        transcriber = Transcriber(
            model,
            no_speech_threshold=config.whisper_no_speech_threshold,
            log_prob_threshold=config.whisper_log_prob_threshold,
            hallucination_blocklist=config.stt_hallucination_blocklist,
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
        readings=config.tts_readings,
        # HTTP 層のタイムアウトも config に合わせる(既定 15s を上書き)。
        timeout=aiohttp.ClientTimeout(total=config.tts_timeout_s),
    )
    llm_stream = functools.partial(
        stream_chat,
        base_url=config.ollama_url,
        session=session,
        num_predict=config.llm_num_predict,
    )
    # 外部API検索(天気等)。weather プロバイダが OPENWEATHER_API_KEY を環境変数から読む。
    api_search = functools.partial(_api_search, session=session, config=config)

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
        api_search=api_search,
        relationship=relationship,
        max_sentences_per_turn=config.max_sentences_per_turn,
        clock=_clock_for_config(config),
        place=_display_place(config),
        screen_context=screen_context,
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


def _lan_ip() -> str:
    """この PC の LAN IP を推定する(外部へ送信はしない)。失敗時は 127.0.0.1。"""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


async def _warm_up(orch, config, loop) -> None:
    """各ステージ(TTS/LLM/STT/VAD)の初回コールドコストを会話開始前に消化する。

    最大の初回コストは LLM(Ollama)の重み VRAM ロード + 初回 prefill。これを
    マイク開始前に払うことで、最初の発話への応答遅延を無くす。各段は失敗しても致命でない。
    """
    # TTS: 初回合成のモデル/参照キャッシュ確立コスト。
    t0 = time.perf_counter()
    print("Warming up TTS...")
    try:
        await asyncio.wait_for(orch.tts("ウォームアップ。"), timeout=config.tts_timeout_s)
        print(f"TTS warm-up done ({time.perf_counter() - t0:.2f}s)")
    except Exception:
        logger.warning("TTS warm-up failed; continuing")

    # LLM: 初回 /api/chat は重みの VRAM ロード + 初回 prefill を払う(最大の初回コスト)。
    t0 = time.perf_counter()
    print("Warming up LLM...")
    try:
        async with contextlib.aclosing(
            orch.llm_stream(
                [{"role": "user", "content": "こんにちは"}], model=config.ollama_model
            )
        ) as gen:
            async for _ in gen:
                break   # 最初のトークンでロード+prefill完了。残りは捨てる。
        print(f"LLM warm-up done ({time.perf_counter() - t0:.2f}s)")
    except Exception:
        logger.warning("LLM warm-up failed; continuing")

    # STT: faster-whisper の初回推論カーネル(cuDNN/cuBLAS)初期化を消化。
    t0 = time.perf_counter()
    print("Warming up STT...")
    try:
        import numpy as np

        from kotoha.config import SAMPLE_RATE_HZ

        dummy = np.random.randn(SAMPLE_RATE_HZ).astype(np.float32) * 0.01
        await asyncio.wait_for(
            loop.run_in_executor(None, orch.transcriber.transcribe, dummy),
            timeout=config.stt_timeout_s,
        )
        print(f"STT warm-up done ({time.perf_counter() - t0:.2f}s)")
    except Exception:
        logger.warning("STT warm-up failed; continuing")

    # VAD: silero+torch のロードをマイク開始前に済ませ、最初の発話検出の遅れを防ぐ。
    try:
        orch._get_segmenter(config.local_user_id)
        orch._get_bargein_detector(config.local_user_id)
    except Exception:
        logger.warning("VAD warm-up failed; continuing")


async def run_local(config: Config) -> None:
    """ローカル(マイク+スピーカ)で会話ループを常駐させる。integration 専用。"""
    # .env からの環境変数読込(任意)。GEMINI_API_KEY 等をリポジトリ外に置くため。
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
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

        # 画面知覚の別バックエンド(VII 等)を指すときだけ、非致命に疎通確認する。
        # down でも会話は best-effort で続くため raise しない。
        aux_status = await check_aux_endpoints(session, config=config)
        for name, ok in aux_status.items():
            print(f"[health] {name}: {'OK' if ok else 'DOWN (best-effort, continuing)'}")
            if not ok:
                logger.warning("%s endpoint unreachable; perception/background runs degraded", name)

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

        # 画面知覚(任意・既定OFF)。VLM は base_url で別バックエンド(VII 等)を指せる。
        # screen_ctx は memory/relationship の background_gate に渡すため、ここで先に作る。
        screen_ctx = None
        screen_tasks = []
        if config.screen_perception_enabled:
            screen_ctx = ScreenContext(summary_max_age_s=config.screen_summary_max_age_s)
            if config.screen_capture_backend == "dxcam":
                capturer = DxcamCapturer(max_long_edge=config.screen_capture_max_long_edge)
            else:
                capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)
            describe = functools.partial(
                vlm_describe,
                model=config.vlm_perception_model,
                base_url=config.vlm_perception_url or config.ollama_url,
                prompt=config.vlm_perception_prompt,
                api=config.vlm_perception_api,
                session=session,
                timeout_s=config.vlm_perception_timeout_s,
            )
            perceiver = ScreenPerceiver(
                capturer=capturer, describe=describe, screen_ctx=screen_ctx,
                normal_interval_s=config.screen_normal_interval_s,
                realtime_interval_s=config.screen_game_realtime_interval_s,
                poll_s=config.screen_game_poll_s,
            )
            game_loop = GameModeLoop(screen_ctx=screen_ctx, config=config)
            screen_tasks = [
                loop.create_task(perceiver.run()),
                loop.create_task(game_loop.run()),
            ]
            print("[screen] perception enabled "
                  f"(backend={config.screen_capture_backend}, vlm={config.vlm_perception_model})")

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
                background_gate=(screen_ctx.background_llm_allowed if screen_ctx else None),
            )
            print(f"[memory] enabled (store={config.memory_path})")

        relationship = None
        if config.relationship_enabled:
            rstore = RelationshipStore.load(
                config.relationship_path,
                defaults={
                    "affection": config.relationship_init_affection,
                    "friendship": config.relationship_init_friendship,
                    "trust": config.relationship_init_trust,
                    "respect": config.relationship_init_respect,
                    "mood": config.relationship_init_mood,
                },
            )
            relationship = RelationshipManager(
                store=rstore, config=config, session=session, loop=loop,
                background_gate=(screen_ctx.background_llm_allowed if screen_ctx else None),
            )
            print(
                f"[relationship] enabled (affection={rstore.affection}, "
                f"mood={rstore.mood}, r18={'on' if relationship.r18_unlocked() else 'off'})"
            )
        # リモート音声モードでは別端末のブラウザのマイク/スピーカーを使う。
        # その場合 player は RemotePlayer を使い、ローカルの mic/speaker は使わない。
        remote_server = None
        player = None
        if config.remote_audio_enabled:
            from kotoha.remote.server import RemoteAudioServer

            remote_server = RemoteAudioServer(
                config=config, loop=loop, user_id=config.local_user_id,
                token=config.remote_audio_token or None,
            )
            player = remote_server.player

        orch = build_orchestrator(
            config,
            session=session,
            loop=loop,
            events=events,
            on_amplitude=on_amplitude,
            memory=memory,
            relationship=relationship,
            player=player,
            screen_context=screen_ctx,
        )
        # ウォームアップ: 各ステージの初回コールドコスト(モデルのVRAMロード/カーネル初期化)を
        # 会話開始前に消化し、最初の応答の遅延を無くす。いずれも失敗しても致命ではない。
        await _warm_up(orch, config, loop)

        mic = None
        if remote_server is not None:
            remote_server.set_on_audio(make_on_audio(orch))
            await remote_server.start()
            print(
                f"[remote] 別端末のブラウザで開く: "
                f"https://{_lan_ip()}:{config.remote_audio_port}/?t={remote_server.token}"
            )
            print("  自己署名証明書の警告は許可してください。Ctrl+C で終了。")
        else:
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
            for t in screen_tasks:
                t.cancel()
            if screen_tasks:
                # キャンセル完了まで待ち、run() の finally でキャプチャ資源を解放させる。
                await asyncio.gather(*screen_tasks, return_exceptions=True)
            if mic is not None:
                mic.stop()
            if remote_server is not None:
                await remote_server.stop()
            if memory is not None:
                await memory.aclose()
            if relationship is not None:
                await relationship.aclose()
            if bridge is not None:
                await bridge.stop()


def main() -> None:
    # .env を Config 構築より先に読み、推論先・画面知覚の上書きを反映する。
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    try:
        asyncio.run(run_local(build_config()))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
