"""画面知覚の共有状態。最新の画面要約と現在モードをスレッドセーフに保持する。

背景の知覚ループ(書き手)と orchestrator の会話ターン(読み手)を疎結合にする。
モードは "normal" | "game_powersave" | "game_realtime"。
"""

import threading
import time


class ScreenContext:
    def __init__(self, *, summary_max_age_s: float = 30.0, clock=time.monotonic):
        self._max_age = summary_max_age_s
        self._clock = clock
        self._lock = threading.Lock()
        self._summary = ""
        self._app = ""
        self._ts = None
        self._mode = "normal"

    def set_summary(self, text: str, app: str = "") -> None:
        with self._lock:
            self._summary = (text or "").strip()
            self._app = (app or "").strip()
            self._ts = self._clock()

    def touch(self) -> None:
        """既存要約の鮮度だけ更新する(内容は変えない)。要約が無ければ何もしない。

        画面が静止して同じフレームが続くとき、再要約せずに鮮度を保つために使う。
        """
        with self._lock:
            if self._summary:
                self._ts = self._clock()

    def get_summary(self) -> str | None:
        """有効な最新要約。未設定・空・期限切れは None。"""
        with self._lock:
            if not self._summary or self._ts is None:
                return None
            if (self._clock() - self._ts) > self._max_age:
                return None
            return self._summary

    def get_app(self) -> str:
        """有効な最新要約があるときの前面アプリ名。無効・期限切れ・未設定は ""。"""
        with self._lock:
            if not self._summary or self._ts is None:
                return ""
            if (self._clock() - self._ts) > self._max_age:
                return ""
            return self._app

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._mode = mode

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def background_llm_allowed(self) -> bool:
        """省力型ゲームモード中は会話以外のLLM処理を止める。"""
        return self.mode != "game_powersave"
