class SentenceSplitter:
    """トークンストリームを句点境界で文に区切る。"""

    def __init__(self, endings: str = "。．！？!?\n"):
        self._endings = set(endings)
        self._buf: list[str] = []

    def push(self, token: str) -> list[str]:
        out: list[str] = []
        for ch in token:
            self._buf.append(ch)
            if ch in self._endings:
                sentence = "".join(self._buf).strip()
                if sentence:
                    out.append(sentence)
                self._buf = []
        return out

    def flush(self) -> str:
        sentence = "".join(self._buf).strip()
        self._buf = []
        return sentence
