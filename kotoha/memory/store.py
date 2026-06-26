import json
import logging
import os

logger = logging.getLogger(__name__)


class MemoryStore:
    """3層記憶＋生ログバッファを保持し JSON で永続化する。

    long_term:str / short_term:list[str] / raw_window:list[dict] /
    pending_raw:list[dict] / turns_since_compress:int。
    不変記憶(persona.py)はここには含めない。
    """

    def __init__(self, path: str):
        self.path = path
        self.long_term: str = ""
        self.short_term: list[str] = []
        self.raw_window: list[dict] = []
        self.pending_raw: list[dict] = []
        self.turns_since_compress: int = 0

    @classmethod
    def load(cls, path: str) -> "MemoryStore":
        store = cls(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return store   # 欠損/破損は空状態で開始
        store.long_term = data.get("long_term", "")
        store.short_term = list(data.get("short_term", []))
        store.raw_window = list(data.get("raw_window", []))
        store.pending_raw = list(data.get("pending_raw", []))
        store.turns_since_compress = int(data.get("turns_since_compress", 0))
        return store

    def to_dict(self) -> dict:
        return {
            "long_term": self.long_term,
            "short_term": self.short_term,
            "raw_window": self.raw_window,
            "pending_raw": self.pending_raw,
            "turns_since_compress": self.turns_since_compress,
        }

    def save(self) -> None:
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)   # 原子的差し替え
        except OSError:
            logger.warning("failed to save memory to %s; continuing", self.path)
