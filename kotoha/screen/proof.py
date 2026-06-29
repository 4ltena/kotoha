"""画面知覚だけを単体起動して目視確認する proof CLI。

GPT-SoVITS とマイクには触れない。build_config() で .env を反映し、実キャプチャと
実 VLM で知覚ループを回して要約と PerceptionStats を表示する。`python -m kotoha.screen.proof`。
"""

import argparse
import asyncio
import functools

import aiohttp

from kotoha.config import build_config
from kotoha.llm.vlm_client import vlm_describe
from kotoha.screen.capture import DxcamCapturer, MssCapturer
from kotoha.screen.detector import get_foreground_info, is_game_active, resolve_mode
from kotoha.screen.perceiver import ScreenPerceiver
from kotoha.screen.state import ScreenContext
from kotoha.screen.stats import PerceptionStats


async def run_proof(*, perceiver, screen_ctx, stats, cycles, out=print) -> None:
    """知覚ループを cycles 回まわし、各サイクルの要約と stats を表示する(実機/テスト共用)。"""
    for i in range(cycles):
        updated = await perceiver.tick()
        out(f"[{i + 1}/{cycles}] updated={updated} summary={screen_ctx.get_summary()!r}")
        out("  " + stats.summary_line())


def _build_describe(config, session):
    return functools.partial(
        vlm_describe,
        model=config.vlm_perception_model,
        base_url=config.vlm_perception_url or config.ollama_url,
        prompt=config.vlm_perception_prompt,
        api=config.vlm_perception_api,
        session=session,
        timeout_s=config.vlm_perception_timeout_s,
    )


async def _main(args) -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    config = build_config()
    backend = args.backend or config.screen_capture_backend
    if backend == "dxcam":
        capturer = DxcamCapturer(max_long_edge=config.screen_capture_max_long_edge)
    else:
        capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)

    fg = get_foreground_info()
    active = is_game_active(
        fg, detect_fullscreen=config.screen_game_detect_fullscreen,
        process_names=config.screen_game_process_names,
    )
    print(f"[foreground] {fg} -> {resolve_mode(active, config.screen_game_mode)}")
    print(f"[vlm] model={config.vlm_perception_model} "
          f"url={config.vlm_perception_url or config.ollama_url} api={config.vlm_perception_api}")

    stats = PerceptionStats()
    screen_ctx = ScreenContext(summary_max_age_s=config.screen_summary_max_age_s)
    timeout = aiohttp.ClientTimeout(total=None, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        perceiver = ScreenPerceiver(
            capturer=capturer, describe=_build_describe(config, session),
            screen_ctx=screen_ctx,
            normal_interval_s=config.screen_normal_interval_s,
            realtime_interval_s=config.screen_game_realtime_interval_s,
            poll_s=config.screen_game_poll_s, stats=stats,
            change_threshold=config.screen_change_hash_threshold,
            get_foreground=lambda: (get_foreground_info() or {}).get("process", ""),
        )
        if args.duration:
            deadline = asyncio.get_running_loop().time() + args.duration
            while asyncio.get_running_loop().time() < deadline:
                await run_proof(perceiver=perceiver, screen_ctx=screen_ctx,
                                stats=stats, cycles=1)
                await asyncio.sleep(config.screen_normal_interval_s)
        else:
            await run_proof(perceiver=perceiver, screen_ctx=screen_ctx,
                            stats=stats, cycles=args.cycles)
        try:
            perceiver._executor.shutdown(wait=False)
        except Exception:
            pass
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="screen-perception proof")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--duration", type=float, default=0.0, help="秒。指定時は時間優先")
    parser.add_argument("--backend", choices=["mss", "dxcam"], default=None)
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    import sys

    sys.exit(main())
