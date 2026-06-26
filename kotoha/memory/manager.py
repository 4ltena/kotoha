import asyncio
import logging

from kotoha.llm import persona
from kotoha.memory import composer
from kotoha.memory.compressor import compress_turns
from kotoha.memory.promoter import promote

logger = logging.getLogger(__name__)


class MemoryManager:
    """会話状態を保持し、圧縮(4b)・昇格(Gemini)をバックグラウンド起動する窓口。"""

    def __init__(
        self,
        *,
        store,
        config,
        session,
        loop,
        immutable_prompt: str = persona.IMMUTABLE_PROMPT,
        gemini_models=None,
        api_key=None,
        compress_fn=compress_turns,
        promote_fn=promote,
        spawn=None,
    ):
        self.store = store
        self.config = config
        self._session = session
        self._loop = loop
        self._immutable = immutable_prompt
        self._gemini_models = list(gemini_models or [])
        self._api_key = api_key
        self._compress_fn = compress_fn
        self._promote_fn = promote_fn
        self._spawn = spawn or self._default_spawn
        self.W = config.memory_keep_recent_turns
        self.N = config.memory_compress_interval
        self.M = config.memory_promote_threshold
        self._short_term_max = config.memory_short_term_max
        self._compress_lock = asyncio.Lock()
        self._promote_lock = asyncio.Lock()
        self._bg: set = set()
        if not (self._api_key and self._gemini_models):
            logger.warning("memory promotion disabled (no GEMINI_API_KEY or no model)")

    # ---- 同期 API（主対話スレッド/ループから呼ぶ。軽量）----
    def add_user(self, text: str) -> None:
        self.store.raw_window.append({"role": "user", "content": text})

    def build_messages(self) -> list[dict]:
        return composer.build_messages(
            immutable=self._immutable,
            long_term=self.store.long_term,
            short_term=self.store.short_term,
            raw_window=self.store.raw_window,
        )

    def on_turn_end(self, assistant_text: str) -> None:
        self.store.raw_window.append({"role": "assistant", "content": assistant_text})
        max_msgs = 2 * self.W
        while len(self.store.raw_window) > max_msgs:
            self.store.pending_raw.append(self.store.raw_window.pop(0))
        self.store.turns_since_compress += 1
        self.store.save()
        if self.store.turns_since_compress >= self.N and self.store.pending_raw:
            self._spawn(self._run_compress())

    async def aclose(self) -> None:
        self.store.save()

    # ---- バックグラウンド ----
    async def _run_compress(self) -> None:
        if self._compress_lock.locked():
            return   # 単発化: 走行中ならスキップ
        async with self._compress_lock:
            if not self.store.pending_raw:
                return
            batch = list(self.store.pending_raw)
            try:
                entries = await self._compress_fn(
                    batch,
                    model=self.config.memory_compress_model,
                    session=self._session,
                    base_url=self.config.ollama_url,
                )
            except Exception:
                logger.warning("memory compression failed; will retry next time")
                return   # pending を捨てない
            del self.store.pending_raw[:len(batch)]
            self.store.short_term.extend(entries)
            if len(self.store.short_term) > self._short_term_max:
                del self.store.short_term[: len(self.store.short_term) - self._short_term_max]
            self.store.turns_since_compress = 0
            self.store.save()
            if len(self.store.short_term) >= self.M:
                self._spawn(self._run_promote())

    async def _run_promote(self) -> None:
        if not (self._api_key and self._gemini_models):
            return
        if self._promote_lock.locked():
            return
        async with self._promote_lock:
            snapshot = list(self.store.short_term)
            if len(snapshot) < self.M:
                return
            try:
                new_long = await self._promote_fn(
                    self.store.long_term,
                    snapshot,
                    model_chain=self._gemini_models,
                    api_key=self._api_key,
                    session=self._session,
                )
            except Exception:
                logger.warning("memory promotion failed; keeping short_term")
                return
            self.store.long_term = new_long
            del self.store.short_term[:len(snapshot)]   # 昇格分のみ除去
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
            logger.error("memory background task failed", exc_info=exc)
