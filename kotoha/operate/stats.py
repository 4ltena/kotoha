"""操作ループの計数とグラウンディングレイテンシをスレッドセーフに保持する観測専用オブジェクト。

会話にも操作判断にも影響しない。記録メソッドは例外を投げない。PerceptionStats と対称。
"""

import threading

_COUNTERS = ("intents", "grounded", "executed", "confirmed_pending",
             "refused", "expired", "aborted")


class OperationStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {k: 0 for k in _COUNTERS}
        self._failures = {}
        self._ground_ms_sum = 0.0
        self._ground_n = 0

    def record(self, kind: str) -> None:
        with self._lock:
            if kind in self._counts:
                self._counts[kind] += 1

    def record_failure(self, kind: str) -> None:
        with self._lock:
            self._failures[kind] = self._failures.get(kind, 0) + 1

    def record_ground_ms(self, ms: float) -> None:
        with self._lock:
            self._ground_ms_sum += ms
            self._ground_n += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg = self._ground_ms_sum / self._ground_n if self._ground_n else 0.0
            return {
                **dict(self._counts),
                "failures": dict(self._failures),
                "avg_ground_ms": avg,
            }

    def summary_line(self) -> str:
        s = self.snapshot()
        fails = sum(s["failures"].values())
        return (
            f"intents={s['intents']} grounded={s['grounded']} exec={s['executed']} "
            f"confirm={s['confirmed_pending']} refused={s['refused']} "
            f"expired={s['expired']} aborted={s['aborted']} fail={fails}"
        )
