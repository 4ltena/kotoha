import numpy as np


def resample_linear(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """線形補間でリサンプル。float32 を返す。

    注意: これは **アンチエイリアス用ローパスを掛けない**単純な線形補間。
    48kHz->16kHz では 8kHz 超の成分が折り返す可能性がある(faster-whisper の
    要件 float32/mono/16k/[-1,1] は満たすが、品質を重視するなら
    scipy.signal.resample_poly や torchaudio のリサンプラ(ローパス付き)へ
    置換すること)。フェーズ1では音声会話用途として許容(点13)。
    """
    x = np.asarray(x, dtype=np.float32)
    if len(x) == 0:
        return np.zeros(0, dtype=np.float32)
    if src_rate == dst_rate:
        return x
    dst_len = int(round(len(x) * dst_rate / src_rate))
    if dst_len <= 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0.0, len(x) - 1, num=dst_len)
    return np.interp(src_idx, np.arange(len(x)), x).astype(np.float32)


def pcm_s16le_to_float32_mono_16k(
    pcm: bytes,
    src_rate: int = 48000,
    src_channels: int = 2,
    dst_rate: int = 16000,
) -> np.ndarray:
    """Discord s16le PCM を 16kHz mono float32([-1,1])へ変換。"""
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    i16 = np.frombuffer(pcm, dtype=np.int16)
    if src_channels == 2:
        if len(i16) % 2:
            i16 = i16[:-1]
        mono = i16.astype(np.float32).reshape(-1, 2).mean(axis=1) / 32768.0
    else:
        mono = i16.astype(np.float32) / 32768.0
    return resample_linear(mono, src_rate, dst_rate)
