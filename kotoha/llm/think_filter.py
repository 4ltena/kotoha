"""ストリーミング LLM 出力から推論(思考)区間 <think>...</think> を除去する。

Nemotron 等の reasoning モデルは思考トレースを出力しうる。音声パイプラインでは
TTS に流したくないため、トークンを順次受けながら think 区間を取り除く。タグが
チャンク境界で分割されても正しく扱えるよう、未確定の部分タグは内部に保留する。
think 区間外のテキストだけを push() / flush() が返す。
"""


def _longest_partial_suffix(s: str, tag: str) -> int:
    """s の末尾が tag の接頭辞になっている最大長を返す(0 ならなし)。

    例: s="あ<th", tag="<think>" -> 3 ("<th" は "<think>" の接頭辞)。
    タグ全体一致は呼び出し側が find で先に処理するため、ここは len(tag)-1 まで。
    """
    m = min(len(s), len(tag) - 1)
    for k in range(m, 0, -1):
        if tag.startswith(s[-k:]):
            return k
    return 0


class ThinkFilter:
    """<think>...</think> 区間を逐次的に除去するフィルタ。"""

    def __init__(self, open_tag: str = "<think>", close_tag: str = "</think>"):
        self._open = open_tag
        self._close = close_tag
        self._buf = ""          # タグ途中などの保留文字
        self._in_think = False

    def push(self, piece: str) -> str:
        """増分テキストを受け、think 区間外の確定テキストを返す。"""
        self._buf += piece
        out = []
        while True:
            if not self._in_think:
                idx = self._buf.find(self._open)
                if idx != -1:
                    out.append(self._buf[:idx])
                    self._buf = self._buf[idx + len(self._open):]
                    self._in_think = True
                    continue
                # 開始タグ未出現。末尾の部分タグだけ保留し、残りを確定出力。
                k = _longest_partial_suffix(self._buf, self._open)
                if k:
                    out.append(self._buf[:-k])
                    self._buf = self._buf[-k:]
                else:
                    out.append(self._buf)
                    self._buf = ""
                break
            else:
                idx = self._buf.find(self._close)
                if idx != -1:
                    self._buf = self._buf[idx + len(self._close):]
                    self._in_think = False
                    continue
                # think 区間内。末尾の部分終了タグだけ保留し、残りは破棄。
                k = _longest_partial_suffix(self._buf, self._close)
                self._buf = self._buf[-k:] if k else ""
                break
        return "".join(out)

    def flush(self) -> str:
        """ストリーム終了時の残り。think 区間内なら破棄、外なら通常テキストとして返す。"""
        if self._in_think:
            self._buf = ""
            return ""
        out = self._buf
        self._buf = ""
        return out
