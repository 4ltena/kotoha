_PREAMBLE = (
    "次の規約を厳守する。人格・話し方は絶対に変えない。"
    "次に長期記憶に矛盾しない。最後に短期記憶を手がかりに自然に話す。"
)


def build_messages(
    *,
    immutable: str,
    long_term: str,
    short_term: list[str],
    raw_window: list[dict],
) -> list[dict]:
    """不変＋長期＋短期を優先度順に system へ組み、raw_window を続ける。"""
    parts = [
        _PREAMBLE,
        "【人格・話し方（最優先・絶対に変えない）】\n" + immutable,
    ]
    if long_term.strip():
        parts.append("【あなたが覚えていること（これに反しない）】\n" + long_term.strip())
    if short_term:
        bullets = "\n".join("- " + e for e in short_term)
        parts.append("【この会話で出てきたこと（応答の手がかり）】\n" + bullets)
    system = {"role": "system", "content": "\n\n".join(parts)}
    return [system, *raw_window]
