"""回答叙述语言与显示语言是否一致：确定性判定，先于 LLM 裁判（E2）。

按「连续汉字片段数」与「纯字母英文单词数」的占比判断主体语言。代码片段、指标代码、
版本号、数字和货币不计；英文回答里夹一个中文商品名不会被判成中文。
"""

from __future__ import annotations

import re
from typing import Final

_CODE_SPAN: Final = re.compile(r"`[^`]*`")
_CJK_RUN: Final = re.compile(r"[一-鿿]+")
_LATIN_TOKEN: Final = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def narrative_matches_locale(answer: str, locale: str) -> bool:
    text = _CODE_SPAN.sub(" ", answer)
    chinese = len(_CJK_RUN.findall(text))
    english = sum(1 for token in _LATIN_TOKEN.findall(text) if len(token) > 1 and token.isalpha())
    if not chinese and not english:
        return True
    mostly_chinese = chinese >= english
    return mostly_chinese if locale == "zh-CN" else not mostly_chinese
