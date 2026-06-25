"""オーバーレイ等への状態通知 events シンクの no-op 実装。

events シンクのダックタイプ I/F:
    state(value: str) -> None   # "idle" | "listening" | "thinking" | "speaking"
    mouth(level: float) -> None # 0.0–1.0 の口開度

NullEvents は何もしない既定実装。OverlayBridge(SP2)が同 I/F を実装する。
"""


class NullEvents:
    """何もしない events シンク(既定)。"""

    def state(self, value: str) -> None:
        return None

    def mouth(self, level: float) -> None:
        return None
