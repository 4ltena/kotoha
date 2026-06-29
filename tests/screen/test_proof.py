import base64
import io

from PIL import Image

from kotoha.screen.proof import run_proof
from kotoha.screen.stats import PerceptionStats
from kotoha.screen.state import ScreenContext
from kotoha.screen.perceiver import ScreenPerceiver


def _frame_b64(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _Cap:
    def capture(self):
        return _frame_b64((100, 100, 100))


async def test_run_proof_prints_summary_and_stats_each_cycle():
    ctx = ScreenContext(summary_max_age_s=1e9, clock=lambda: 0.0)
    stats = PerceptionStats()

    async def describe(image_b64):
        return "画面にエディタ。"

    p = ScreenPerceiver(
        capturer=_Cap(), describe=describe, screen_ctx=ctx,
        normal_interval_s=4.0, realtime_interval_s=0.5, stats=stats,
    )
    lines = []
    await run_proof(perceiver=p, screen_ctx=ctx, stats=stats, cycles=2, out=lines.append)
    text = "\n".join(lines)
    assert "画面にエディタ" in text       # 要約を表示
    assert "captures=" in text           # stats を表示
    assert "[1/2]" in text and "[2/2]" in text
