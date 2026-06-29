"""操作グラウンディングだけを単体起動して目視確認する proof CLI。

GPT-SoVITS とマイクには触れない。指定の指示を実画面でグラウンディングして、前面アプリ・
region・正規化/絶対座標・dry-run の「ここを押す」を表示する。`--arm` で初めて実作動する。
Holo2 の実座標出力形式（0〜1000 正規化）の裏取りにも使う。`python -m kotoha.operate.proof "指示"`。
"""

import argparse
import asyncio
import functools

from kotoha.config import build_config
from kotoha.operate.actions import ActionRequest
from kotoha.operate.actuator import Actuator
from kotoha.operate.grounding import ground_target


async def run_proof(*, instruction, capture_region, ground, actuator, out=print) -> None:
    """1 指示をグラウンディングして region・座標・実行結果を表示する（実機/テスト共用）。"""
    cap = capture_region()
    if not cap:
        out("[capture] FAILED")
        return
    image_b64, region = cap
    out(f"[region] {region.left},{region.top},{region.width},{region.height}")
    result = await ground(image_b64, instruction=instruction, region=region)
    if result is None:
        out("[ground] no coordinates")
        return
    out(f"[abs] {result.x},{result.y}")
    out(f"[raw] {result.raw!r}")
    out("COORDINATE_FORMAT: 0-1000 normalized (assumed) — verify against raw above")
    ok = actuator.execute(ActionRequest("click", target=instruction), coords=(result.x, result.y))
    mode = "dry-run" if actuator.is_dry_run() else "ARMED"
    out(f"[execute:{mode}] ok={ok}")


async def _main(args) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    config = build_config()
    from kotoha.screen.capture import MssCapturer
    from kotoha.screen.detector import get_foreground_info
    capturer = MssCapturer(max_long_edge=config.screen_capture_max_long_edge)
    g_url = config.grounding_url or config.vlm_perception_url or config.ollama_url
    print(f"[foreground] {get_foreground_info()}")
    print(f"[grounding] model={config.grounding_model} url={g_url} api={config.grounding_api}")
    ground = functools.partial(
        ground_target, model=config.grounding_model, base_url=g_url,
        api=config.grounding_api, session=None,
        timeout_s=config.grounding_timeout_s, prompt=config.grounding_prompt,
    )
    actuator = Actuator(
        dry_run=not args.arm, kill_hotkey=config.operation_kill_hotkey,
        max_actions=config.operation_max_actions_per_command,
    )
    try:
        await run_proof(instruction=args.instruction, capture_region=capturer.capture_with_region,
                        ground=ground, actuator=actuator)
    finally:
        actuator.close()
        capturer.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="operation-grounding proof")
    parser.add_argument("instruction", help="例: その検索ボタン")
    parser.add_argument("--arm", action="store_true", help="実作動する(既定は dry-run)")
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    import sys
    sys.exit(main())
