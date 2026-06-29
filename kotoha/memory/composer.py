_PREAMBLE = (
    "次の規約を厳守する。人格・話し方は絶対に変えない。"
    "返答は短い会話文だけにし、通常1文、必要なときだけ2文で自然に終える。"
    "次に長期記憶に矛盾しない。最後に短期記憶を手がかりに自然に話す。"
)

_WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")


def _time_band(hour: int) -> str:
    """時(0-23)を日本語の時間帯ラベルに変換する。"""
    if 5 <= hour < 11:
        return "朝"
    if 11 <= hour < 17:
        return "昼"
    if 17 <= hour < 19:
        return "夕方"
    if 19 <= hour < 24:
        return "夜"
    return "深夜"   # 0:00-4:59


def format_time_context(now) -> str:
    """datetime から現在時刻の文脈文字列を作る(純関数。now を渡すのでテスト容易)。"""
    wd = _WEEKDAYS[now.weekday()]
    return (
        f"現在は {now.year}-{now.month:02d}-{now.day:02d} ({wd}) "
        f"{now.hour:02d}:{now.minute:02d} ごろ、時間帯は「{_time_band(now.hour)}」。"
    )


def build_messages(
    *,
    immutable: str,
    long_term: str,
    short_term: list[str],
    raw_window: list[dict],
    time_context: str = "",
) -> list[dict]:
    """不変＋時刻＋長期＋短期を優先度順に system へ組み、raw_window を続ける。"""
    parts = [
        _PREAMBLE,
        "【人格・話し方（最優先・絶対に変えない）】\n" + immutable,
    ]
    if time_context:
        parts.append("【いまの時刻】\n" + time_context)
    if long_term.strip():
        parts.append("【あなたが覚えていること（これに反しない）】\n" + long_term.strip())
    if short_term:
        bullets = "\n".join("- " + e for e in short_term)
        parts.append("【この会話で出てきたこと（応答の手がかり）】\n" + bullets)
    system = {"role": "system", "content": "\n\n".join(parts)}
    return [system, *raw_window]
