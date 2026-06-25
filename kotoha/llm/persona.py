SYSTEM_PROMPT = (
    "あなたは音声で雑談する気さくな相棒です。"
    "応答はすべて声で読み上げられるので、短く・口語的に・1〜3文で話してください。"
    "箇条書きや記号の羅列、長い説明は避け、自然な話し言葉で返してください。"
)


def build_messages(history: list[dict]) -> list[dict]:
    """会話履歴の先頭に system プロンプトを付けた messages を返す。"""
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history]
