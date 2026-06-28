"""VLM の画面要約をプレーン化し、短い会話文脈に収める純関数。

ローカル VLM(4b)はプロンプトで「最大2文・装飾なし」と指示しても、2〜3文や
Markdown 装飾(**太字**、`code`、箇条書き)を返すことがある。【画面の様子】へ
注入する前にここで均し、装飾・冗長が文脈へ漏れないようにする。失敗時は素通し。
"""

import re

from kotoha.llm.sentence_splitter import SentenceSplitter

# **太字** / *斜体* / __強調__ / `code` を剥がす。
_EMPHASIS_RE = re.compile(r"\*\*|\*|__|`+")
# 行頭の見出し(#)・引用(>)・箇条書き(- ・ • ·)・番号(1. 1) 1、)を剥がす。
_BULLET_RE = re.compile(r"^[ \t]*(?:[#>]+|[-・·•]+|\d+[.)、])[ \t]*", re.MULTILINE)


def normalize_summary(text, *, max_sentences: int = 2) -> str:
    """要約を装飾除去し最大 max_sentences 文へ詰める。空・失敗時は素直に返す。"""
    if not text:
        return ""
    s = _EMPHASIS_RE.sub("", text)
    s = _BULLET_RE.sub("", s)
    s = re.sub(r"[ \t]*\n+[ \t]*", " ", s)   # 改行は文の連結とみなし空白へ
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    if not s:
        return ""

    splitter = SentenceSplitter()
    sentences = splitter.push(s)              # 句点で区切れた確定文(strip済み)
    out = sentences[:max_sentences]
    if len(out) < max_sentences:
        tail = splitter.flush().strip()       # 句点で終わらない末尾断片
        if tail:
            out.append(tail)
    result = "".join(out).strip()
    return result or s                        # 分割で空になったら均した文字列を返す
