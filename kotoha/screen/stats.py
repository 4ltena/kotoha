"""画面知覚ループの計数とレイテンシをスレッドセーフに保持する観測専用オブジェクト。

perceiver(書き手・ワーカーとループの両スレッド)と CLI・local_app・診断(読み手)を
疎結合にする。会話にも知覚判断にも影響しない。記録メソッドは例外を投げない。
"""

import threading


class PerceptionStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._captures = 0
        self._describes = 0
        self._skips = 0
        self._summary_updates = 0
        self._failures = {"capture": 0, "vlm": 0}
        self._cap_ms_sum = 0.0
        self._cap_ms_last = 0.0
        self._vlm_ms_sum = 0.0
        self._vlm_ms_last = 0.0
        self._mode = "normal"

    def record_capture(self, ms: float) -> None:
        with self._lock:
            self._captures += 1
            self._cap_ms_last = ms
            self._cap_ms_sum += ms

    def record_describe(self, ms: float) -> None:
        with self._lock:
            self._describes += 1
            self._vlm_ms_last = ms
            self._vlm_ms_sum += ms

    def record_skip(self) -> None:
        with self._lock:
            self._skips += 1

    def record_summary_update(self) -> None:
        with self._lock:
            self._summary_updates += 1

    def record_failure(self, kind: str) -> None:
        with self._lock:
            self._failures[kind] = self._failures.get(kind, 0) + 1

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode

    def snapshot(self) -> dict:
        with self._lock:
            cap_avg = self._cap_ms_sum / self._captures if self._captures else 0.0
            vlm_avg = self._vlm_ms_sum / self._describes if self._describes else 0.0
            return {
                "captures": self._captures,
                "describes": self._describes,
                "skips": self._skips,
                "summary_updates": self._summary_updates,
                "failures": dict(self._failures),
                "last_capture_ms": self._cap_ms_last,
                "avg_capture_ms": cap_avg,
                "last_vlm_ms": self._vlm_ms_last,
                "avg_vlm_ms": vlm_avg,
                "mode": self._mode,
            }

    def summary_line(self) -> str:
        s = self.snapshot()
        fails = sum(s["failures"].values())
        return (
            f"captures={s['captures']} describes={s['describes']} "
            f"skips={s['skips']} vlm_avg={s['avg_vlm_ms'] / 1000:.1f}s "
            f"fail={fails} mode={s['mode']}"
        )
