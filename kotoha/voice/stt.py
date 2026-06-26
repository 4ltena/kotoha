import numpy as np


def build_whisper(
    model_size: str = "large-v3-turbo",
    device: str = "cuda",
    compute_type: str = "float16",
):
    from faster_whisper import WhisperModel

    # GPU: device="cuda"/compute_type="float16"、CPU フォールバック: "cpu"/"int8"
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def _normalize(s: str) -> str:
    """末尾の句読点・空白を落として比較用に正規化する。"""
    return s.strip().rstrip("。.!?！？ 　")


class Transcriber:
    """faster-whisper ラッパ。numpy(float32/mono/16k/[-1,1])をそのまま渡す
    (ndarray は decode_audio をバイパスするので形式は呼び出し側保証)。

    幻聴対策: 無音らしいセグメント(no_speech_prob が閾値超)を捨て、既知の幻聴フレーズ
    (「ご視聴ありがとうございました」等)に一致する出力は空にする。
    """

    def __init__(
        self,
        model,
        *,
        language: str = "ja",
        beam_size: int = 5,
        no_speech_threshold: float = 0.6,
        log_prob_threshold: float = -1.0,
        hallucination_blocklist=(),
    ):
        self._model = model
        self._language = language
        self._beam_size = beam_size
        self._no_speech_threshold = no_speech_threshold
        self._log_prob_threshold = log_prob_threshold
        self._blocklist = {_normalize(p) for p in hallucination_blocklist}

    def transcribe(self, audio: np.ndarray) -> str:
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            no_speech_threshold=self._no_speech_threshold,
            log_prob_threshold=self._log_prob_threshold,
            condition_on_previous_text=False,   # 直前テキストへの追従で起きる反復・幻聴を抑制
        )
        # segments は遅延ジェネレータ -> 反復して初めて推論が走る
        kept = []
        for seg in segments:
            if getattr(seg, "no_speech_prob", 0.0) > self._no_speech_threshold:
                continue   # 無音らしい区間は捨てる(幻聴対策)
            kept.append(seg.text)
        text = "".join(kept).strip()
        if _normalize(text) in self._blocklist:
            return ""      # 既知の幻聴フレーズは無視
        return text
