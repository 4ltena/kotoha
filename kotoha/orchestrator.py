import asyncio
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np

from kotoha.config import SAMPLE_RATE_HZ, VAD_WINDOW_SAMPLES
from kotoha.llm import persona as _persona
from kotoha.llm.sentence_splitter import SentenceSplitter
# Task 12 で feed_audio から使用
from kotoha.voice.vad import VadSegmenter, BargeInDetector

logger = logging.getLogger(__name__)

_SENTINEL = object()


def make_on_audio(orch):
    """受信スレッド -> Orchestrator.feed_audio の薄い配線(単体テスト可能)。"""
    def on_audio(user_id, audio):
        orch.feed_audio(user_id, audio)
    return on_audio


class Orchestrator:
    """受信→STT→LLM→文分割→TTS→再生の中央配線。

    TTS 合成と再生を 3 段の asyncio キュー(文 -> 音声 -> 再生)で
    パイプライン化し、LLM 消費を止めずに TTS と再生を重ねる。
    """

    def __init__(
        self,
        *,
        transcriber,
        llm_stream,
        tts,
        player,
        model: str,
        vad_factory,
        persona=_persona,
        history_max_turns: int = 20,
        vad_threshold: float = 0.5,
        vad_silence_ms: int = 400,
        bargein_trigger_ms: int = 250,
        sample_rate: int = SAMPLE_RATE_HZ,
        vad_window: int = VAD_WINDOW_SAMPLES,
        fallback_text: str = "ごめん、うまく聞き取れなかった。",
        stt_timeout: float = 30.0,
        tts_timeout: float = 15.0,
        play_timeout: float = 60.0,
        splitter_factory=SentenceSplitter,
        loop=None,
    ):
        self.transcriber = transcriber
        self.llm_stream = llm_stream
        self.tts = tts
        self.player = player
        self.model = model
        self.vad_factory = vad_factory          # Callable[[], SileroVad]
        self.persona = persona
        self.history: deque = deque(maxlen=history_max_turns * 2)
        self.vad_threshold = vad_threshold
        self.vad_silence_ms = vad_silence_ms
        self.bargein_trigger_ms = bargein_trigger_ms
        self.sample_rate = sample_rate
        self.vad_window = vad_window
        self.fallback_text = fallback_text
        self._stt_timeout = stt_timeout
        self._tts_timeout = tts_timeout
        self._play_timeout = play_timeout
        self.splitter_factory = splitter_factory
        self._loop = loop
        self._turn_task: Optional[asyncio.Task] = None
        self._assistant_buf = ""
        # --- Task 12 で使用する状態 ---
        self._last_speaker: Optional[int] = None
        self._segmenters: dict = {}
        self._bargein_detectors: dict = {}
        self._pending_preroll: dict = {}
        self._sentence_q: Optional[asyncio.Queue] = None
        self._play_q: Optional[asyncio.Queue] = None
        # VAD 推論をループ外へ逃がす単一ワーカースレッド(点12)
        self._vad_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vad")

    # ---- ターンの保存/差し替え ----
    def _save_partial(self) -> None:
        # 中断時点までの bot 発話を履歴へ。冪等(buf を毎回クリア)。
        if self._assistant_buf.strip():
            self.history.append(
                {"role": "assistant", "content": self._assistant_buf.strip()}
            )
        self._assistant_buf = ""

    def _flush_play_queue(self) -> None:
        # barge-in (c): TTS/再生キューをフラッシュ
        for q in (self._sentence_q, self._play_q):
            if q is None:
                continue
            while not q.empty():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break

    def _preempt_turn(self) -> None:
        # 進行中ターンを差し替える前に、中断時点までの bot 発話を退避(点10)。
        self._save_partial()
        self._flush_play_queue()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()

    async def handle_utterance(self, user_id: int, audio: np.ndarray) -> None:
        self._preempt_turn()    # 進行中ターンがあれば partial 保存してから cancel(点10)
        loop = asyncio.get_running_loop()
        self._loop = loop
        # STT: executor で実行し wait_for で上限(点5)。例外は沈黙扱い(点4)。
        try:
            text = await asyncio.wait_for(
                loop.run_in_executor(None, self.transcriber.transcribe, audio),
                timeout=self._stt_timeout,
            )
        except Exception:
            logger.exception("STT failed (user=%s) -> 沈黙扱いでスキップ", user_id)
            return
        text = (text or "").strip()
        if not text:
            return
        self.history.append({"role": "user", "content": text})
        messages = self.persona.build_messages(list(self.history))
        self._turn_task = asyncio.create_task(self._run_turn(messages))
        try:
            await self._turn_task
        except asyncio.CancelledError:
            pass

    async def _run_turn(self, messages: list[dict]) -> None:
        splitter = self.splitter_factory()
        self._assistant_buf = ""
        self._sentence_q = asyncio.Queue()
        self._play_q = asyncio.Queue()
        tasks = [
            asyncio.create_task(self._llm_to_sentences(messages, splitter)),
            asyncio.create_task(self._sentences_to_audio()),
            asyncio.create_task(self._audio_to_playback()),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            raise
        except Exception:
            # LLM/TTS/API/再生失敗 -> ログ + フォールバック発話(点3)
            logger.exception("ターン処理に失敗 -> フォールバック発話")
            for t in tasks:
                t.cancel()
            await self._speak_fallback()
        finally:
            self._save_partial()
            self._sentence_q = None
            self._play_q = None

    async def _llm_to_sentences(self, messages, splitter) -> None:
        # LLM 消費は TTS/再生を待たずに進む(キューへ流すだけ)。
        async for piece in self.llm_stream(messages, model=self.model):
            self._assistant_buf += piece
            for sentence in splitter.push(piece):
                await self._sentence_q.put(sentence)
        tail = splitter.flush()
        if tail:
            await self._sentence_q.put(tail)
        await self._sentence_q.put(_SENTINEL)

    async def _sentences_to_audio(self) -> None:
        # 再生中の文と並行して次文を合成(パイプライン化)。
        while True:
            sentence = await self._sentence_q.get()
            if sentence is _SENTINEL:
                await self._play_q.put(_SENTINEL)
                return
            wav = await asyncio.wait_for(self.tts(sentence), timeout=self._tts_timeout)
            await self._play_q.put(wav)

    async def _audio_to_playback(self) -> None:
        while True:
            wav = await self._play_q.get()
            if wav is _SENTINEL:
                return
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )

    async def _speak_fallback(self) -> None:
        try:
            wav = await asyncio.wait_for(
                self.tts(self.fallback_text), timeout=self._tts_timeout
            )
            await asyncio.wait_for(
                self.player.play_and_wait(wav), timeout=self._play_timeout
            )
        except Exception:
            logger.exception("フォールバック発話にも失敗")

    # ---- VAD ストリーム生成(ユーザー別・用途別に独立した silero を持つ) ----
    def _get_segmenter(self, user_id: int) -> VadSegmenter:
        seg = self._segmenters.get(user_id)
        if seg is None:
            vad = self.vad_factory()   # 新規ステートフル VAD
            seg = VadSegmenter(
                vad.prob, reset_fn=vad.reset,
                threshold=self.vad_threshold, silence_ms=self.vad_silence_ms,
                sample_rate=self.sample_rate, window=self.vad_window,
            )
            self._segmenters[user_id] = seg
        return seg

    def _get_bargein_detector(self, user_id: int) -> BargeInDetector:
        det = self._bargein_detectors.get(user_id)
        if det is None:
            vad = self.vad_factory()   # セグメンタとは別の独立ストリーム
            det = BargeInDetector(
                vad.prob, reset_fn=vad.reset,
                threshold=self.vad_threshold, trigger_ms=self.bargein_trigger_ms,
                sample_rate=self.sample_rate, window=self.vad_window,
            )
            self._bargein_detectors[user_id] = det
        return det

    def _reset_all_vad(self) -> None:
        for s in self._segmenters.values():
            s.reset()
        for d in self._bargein_detectors.values():
            d.reset()

    def _spawn_turn(self, user_id: int, utterance: np.ndarray) -> None:
        task = asyncio.ensure_future(self.handle_utterance(user_id, utterance))
        task.add_done_callback(self._log_task_exception)   # 未捕捉例外を握り潰さない(点4)

    @staticmethod
    def _log_task_exception(task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("utterance task failed", exc_info=exc)

    # ---- barge-in ----
    def request_bargein(self, user_id: Optional[int] = None) -> None:
        # 中断時点までの bot 発話を保存 (§4) -> (c)キューフラッシュ -> (b)LLM中断 -> (a)再生停止
        self._save_partial()
        self._flush_play_queue()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
        self.player.stop()
        # 割り込みユーザーの冒頭(pre-roll)を次のセグメンタへ引き継ぐ(点9)
        if user_id is not None:
            det = self._bargein_detectors.get(user_id)
            if det is not None:
                self._pending_preroll[user_id] = det.drain()
        # idle<->再生中のストリーム切替なので全 VAD 状態をリセット(点1/11/16)
        self._reset_all_vad()

    # ---- 音声ルーティング ----
    def feed_audio(self, user_id: int, audio: np.ndarray) -> None:
        # 受信スレッドから安全に呼べる。torch VAD 推論を専用ワーカースレッドへ
        # 逃がし、受信スレッドもイベントループもブロックしない(点12)。
        self._vad_executor.submit(
            self._route_audio, user_id, np.asarray(audio, dtype=np.float32)
        )

    def _route_audio(self, user_id: int, audio: np.ndarray) -> None:
        # VAD ワーカースレッド(単一)で実行 -> 確定イベントだけループへ marshalling。
        try:
            if self.player.is_playing():
                det = self._get_bargein_detector(user_id)
                if det.push(audio):
                    self._loop.call_soon_threadsafe(self.request_bargein, user_id)
            else:
                seg = self._get_segmenter(user_id)
                pre = self._pending_preroll.pop(user_id, None)
                if pre is not None and len(pre):
                    audio = np.concatenate([pre, audio])   # 割り込み冒頭を欠落させない
                for utterance in seg.push(audio):
                    self._last_speaker = user_id
                    self._loop.call_soon_threadsafe(
                        self._spawn_turn, user_id, utterance
                    )
        except Exception:
            logger.exception("VAD routing failed (user=%s)", user_id)
