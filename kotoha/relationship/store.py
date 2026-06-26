"""関係性パラメータの保持と JSON 永続化。

5値: affection/friendship/trust/respect(0-100) と mood(-50..50, その日の気分)。
last_day は mood の日次調整に使う最終更新日(ISO)。専用ファイルで管理する。
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

FIELDS = ("affection", "friendship", "trust", "respect", "mood")


class RelationshipStore:
    def __init__(self, path, *, affection=90, friendship=90, trust=90,
                 respect=90, mood=40):
        self.path = path
        self.affection = affection
        self.friendship = friendship
        self.trust = trust
        self.respect = respect
        self.mood = mood
        self.last_day = ""

    @classmethod
    def load(cls, path, *, defaults=None):
        """ファイルがあれば読み込み、無ければ defaults(初期値)で開始。破損も defaults。"""
        store = cls(path, **(defaults or {}))
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return store
        for k in FIELDS:
            if k in data:
                setattr(store, k, int(data[k]))
        store.last_day = data.get("last_day", "")
        return store

    def to_dict(self):
        d = {k: getattr(self, k) for k in FIELDS}
        d["last_day"] = self.last_day
        return d

    def save(self):
        try:
            dirp = os.path.dirname(self.path)
            if dirp:
                os.makedirs(dirp, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            logger.warning("failed to save relationship to %s; continuing", self.path)
