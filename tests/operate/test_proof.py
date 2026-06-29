from kotoha.operate.grounding import GroundResult, Region
from kotoha.operate.proof import run_proof


class _Act:
    def __init__(self): self.calls = []
    def execute(self, action, *, coords): self.calls.append(coords); return True
    def aborted(self): return False
    def is_dry_run(self): return True


async def test_run_proof_prints_region_and_coords():
    def cap(): return ("IMG", Region(0, 0, 1000, 1000))

    async def ground(image_b64, *, instruction, region):
        return GroundResult(x=500, y=250, raw="click(500,250)")

    lines = []
    await run_proof(instruction="検索ボタン", capture_region=cap, ground=ground,
                    actuator=_Act(), out=lines.append)
    text = "\n".join(lines)
    assert "[region]" in text and "[abs] 500,250" in text
    assert "COORDINATE_FORMAT" in text
