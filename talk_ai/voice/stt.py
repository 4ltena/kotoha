import numpy as np


def build_whisper(
    model_size: str = "large-v3-turbo",
    device: str = "cuda",
    compute_type: str = "float16",
):
    from faster_whisper import WhisperModel

    # GPU: device="cuda"/compute_type="float16"、CPU フォールバック: "cpu"/"int8"
    return WhisperModel(model_size, device=device, compute_type=compute_type)


class Transcriber:
    """faster-whisper ラッパ。numpy(float32/mono/16k/[-1,1])をそのまま渡す
    (ndarray は decode_audio をバイパスするので形式は呼び出し側保証)。"""

    def __init__(self, model, *, language: str = "ja", beam_size: int = 5):
        self._model = model
        self._language = language
        self._beam_size = beam_size

    def transcribe(self, audio: np.ndarray) -> str:
        audio = np.asarray(audio, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio, language=self._language, beam_size=self._beam_size
        )
        # segments は遅延ジェネレータ -> 反復して初めて推論が走る
        return "".join(seg.text for seg in segments).strip()
