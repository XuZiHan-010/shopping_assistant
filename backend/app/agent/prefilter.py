"""零 LLM 的问题范围前置闸门。

设计见 `openspec/changes/add-question-prefilter-gate/design.md`。切词不依赖任何
分词库：中文按 2~4 字滑窗切分，英文单词与连续数字整体保留——这与知识检索层
`_matches_keywords` 的子串包含匹配天然兼容。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

_CJK_RUN: Final = re.compile(r"[一-鿿]+")
_ALNUM_TOKEN: Final = re.compile(r"[a-zA-Z0-9]+")
_NGRAM_MIN: Final = 2
_NGRAM_MAX: Final = 4

#: 现代汉语功能词的封闭集合，与「无关词黑名单」不同：这份表不随用户提问内容
#: 增长（design.md D3）。只影响候选词是否保留，不单独决定拒绝。
_STOPWORDS: Final = frozenset(
    {
        "请问",
        "什么",
        "怎么",
        "为什么",
        "一下",
        "可以",
        "是否",
        "的话",
        "如何",
        "哪些",
        "哪个",
        "多少",
        "这个",
        "那个",
    }
)


#: 短问候语/寒暄整体匹配，不参与打分——「日常打招呼由模型自然回答」是既有产品行为
#: （proposal.md Why），闸门不得把它们判定为范围外。
_GREETING_PATTERNS: Final = (
    "你好",
    "您好",
    "在吗",
    "在么",
    "谢谢",
    "感谢",
    "嗨",
    "早上好",
    "中午好",
    "下午好",
    "晚上好",
    "hello",
    "hi",
)
#: 问候语判定只用于极短寒暄；超过这个长度大概率夹带了真实问题内容
#: （如「你好，帮我查一下最近的订单量」），必须继续走打分而非直接放行。
_GREETING_MAX_LENGTH: Final = 10


def is_greeting(question: str) -> bool:
    """识别日常问候，不做任何 LLM 调用。"""

    stripped = question.strip().lower()
    if not stripped or len(stripped) > _GREETING_MAX_LENGTH:
        return False
    return any(pattern in stripped for pattern in _GREETING_PATTERNS)


def tokenize(question: str) -> tuple[str, ...]:
    """把原始问题切成候选词，全部小写，过滤停用词，不做任何 LLM 调用。"""

    tokens: list[str] = []
    for run in _CJK_RUN.finditer(question):
        text = run.group()
        length = len(text)
        for size in range(_NGRAM_MIN, _NGRAM_MAX + 1):
            if size > length:
                break
            for start in range(length - size + 1):
                tokens.append(text[start : start + size])
    for match in _ALNUM_TOKEN.finditer(question):
        tokens.append(match.group().lower())
    return tuple(token for token in tokens if token not in _STOPWORDS)


#: `decide` 的判定结果原因，供日志与测试断言。
ALLOW_DISABLED: Final = "disabled"
ALLOW_SESSION_HISTORY: Final = "session_has_history"
ALLOW_GREETING: Final = "greeting"
ALLOW_SCORE: Final = "score"
ALLOW_CORPUS_UNAVAILABLE: Final = "corpus_unavailable"
REJECT_BELOW_THRESHOLD: Final = "below_threshold"

#: `None` 表示语料完全不可用（须 fail open），区别于「语料存在但没命中」的 0 分。
ScoreQuestion = Callable[[Sequence[str]], Awaitable[int | None]]


@dataclass(frozen=True)
class PrefilterDecision:
    allowed: bool
    reason: str
    score: int | None = None
    threshold: int | None = None


async def decide(
    question: str,
    *,
    enabled: bool,
    min_score: int,
    session_has_prior_turn: bool,
    score_question: ScoreQuestion,
) -> PrefilterDecision:
    """零 LLM 判定问题是否落在平台经营问答范围内。

    分支顺序即优先级：前四条命中即放行且不打分（design.md D1/D4/D5/D6）；
    只有全部不命中才真正调用 `score_question`，也是唯一一条可能拒绝的路径。
    """

    if not enabled:
        return PrefilterDecision(allowed=True, reason=ALLOW_DISABLED)
    if session_has_prior_turn:
        return PrefilterDecision(allowed=True, reason=ALLOW_SESSION_HISTORY)
    if is_greeting(question):
        return PrefilterDecision(allowed=True, reason=ALLOW_GREETING)

    try:
        score = await score_question(tokenize(question))
    except Exception:  # 语料读取失败必须 fail open，不得向上传播中断本轮问答
        return PrefilterDecision(allowed=True, reason=ALLOW_CORPUS_UNAVAILABLE)

    if score is None:
        return PrefilterDecision(allowed=True, reason=ALLOW_CORPUS_UNAVAILABLE)
    if score >= min_score:
        return PrefilterDecision(
            allowed=True, reason=ALLOW_SCORE, score=score, threshold=min_score
        )
    return PrefilterDecision(
        allowed=False, reason=REJECT_BELOW_THRESHOLD, score=score, threshold=min_score
    )
