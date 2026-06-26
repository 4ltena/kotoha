"""関係値の更新窓口。ターンごとに背景で 4b 分析を起動し、値を更新する。

主応答を止めないバックグラウンド処理(単発化ガード付き)。日付が変わると mood を
少しだけ基準へ寄せる(気分は引きずるが減衰)。persona へ注入する文脈と、affection が
しきい値以上かの解禁フラグを提供する。
"""

import asyncio
import logging
from datetime import datetime

from kotoha.relationship.analyzer import analyze, apply_deltas

logger = logging.getLogger(__name__)


class RelationshipManager:
    def __init__(self, *, store, config, session, loop,
                 analyze_fn=analyze, spawn=None, clock=None):
        self.store = store
        self.config = config
        self._session = session
        self._loop = loop
        self._analyze_fn = analyze_fn
        self._spawn = spawn or self._default_spawn
        self._clock = clock or datetime.now
        self.r18_threshold = config.relationship_r18_threshold
        self._lock = asyncio.Lock()
        self._bg: set = set()

    # ---- 参照 ----
    def r18_unlocked(self) -> bool:
        return self.store.affection >= self.r18_threshold

    def persona_context(self) -> str:
        s = self.store
        lines = [
            "【ふたりの関係(0-100、moodは-50〜50)】"
            f"親密度={s.affection}, 友情={s.friendship}, 信頼={s.trust}, "
            f"敬意={s.respect}, 今日の気分={s.mood}。",
            "値が高いほど距離が近く心を開いた話し方にし、気分が高いと明るめ、低いと控えめにする。",
        ]
        if self.r18_unlocked():
            extra = self._load_r18_prompt()
            if extra:
                lines.append(extra)
        return "\n".join(lines)

    def _load_r18_prompt(self) -> str:
        """解禁時に足す非公開プロンプトをファイルから読む(git 管理外。無ければ空)。"""
        path = getattr(self.config, "relationship_r18_prompt_path", "")
        if not path:
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    # ---- 更新 ----
    def on_turn(self, user_text: str, context=None) -> None:
        self._maybe_new_day()
        # 背景分析(4b)はVRAM/速度に響くため、無効時は値を固定したまま注入のみにする。
        if getattr(self.config, "relationship_analyze_enabled", True):
            self._spawn(self._run_analyze(user_text, context))

    def _maybe_new_day(self) -> None:
        today = self._clock().date().isoformat()
        if self.store.last_day and self.store.last_day != today:
            # 日が変わったら mood を少し基準(0)へ寄せる(引きずりつつ減衰)。
            self.store.mood = int(self.store.mood * 0.7)
        self.store.last_day = today

    async def _run_analyze(self, user_text, context) -> None:
        if self._lock.locked():
            return   # 単発化: 走行中ならスキップ
        async with self._lock:
            try:
                deltas = await self._analyze_fn(
                    user_text, self.store,
                    model=self.config.relationship_model,
                    session=self._session,
                    base_url=self.config.ollama_url,
                    context=context,
                )
            except Exception:
                logger.warning("relationship analysis failed; keeping values")
                return
            if deltas:
                apply_deltas(self.store, deltas)
                self.store.save()

    async def aclose(self) -> None:
        self.store.save()

    def _default_spawn(self, coro):
        task = self._loop.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        task.add_done_callback(self._log_task_exc)
        return task

    @staticmethod
    def _log_task_exc(task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("relationship background task failed", exc_info=exc)
