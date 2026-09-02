"""零 LLM 的问题范围前置闸门。

设计见 `openspec/changes/add-question-prefilter-gate/design.md`。切词不依赖任何
分词库：中文按 2~4 字滑窗切分，英文单词与连续数字整体保留——这与知识检索层
`_matches_keywords` 的子串包含匹配天然兼容。

Task 5（双语化）：打分语料（知识文档、正式指标目录、商家记忆）几乎全是中文，
英文问题的英文 token 直接拿去打分只会全部落空，误把正当的英文经营提问当成
范围外拒绝。解法不是引入 LLM 翻译，也不是修改语料本身，而是在切词阶段用
`app.localization.catalog` 里从既有中文业务词表反查出的确定性英文同义词表，
把能反查到的英文业务词换算成等价的中文候选词一并送去打分——真正的评分逻辑
（`KnowledgeRetrieval.score_question`）完全不变。反查不到的英文词沿用既有的
「语料不可用」fail open 路径，宁可放行也不误拒。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final

from app.localization.catalog import (
    EN_STOPWORDS,
    ZH_STOPWORDS,
    zh_business_terms_for_english_word,
)

_CJK_RUN: Final = re.compile(r"[一-鿿]+")
_ALNUM_TOKEN: Final = re.compile(r"[a-zA-Z0-9]+")
_NGRAM_MIN: Final = 2
_NGRAM_MAX: Final = 4


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


def _cjk_ngrams(text: str) -> list[str]:
    """把一段连续汉字切成 2~4 字滑窗子串。"""

    length = len(text)
    grams: list[str] = []
    for size in range(_NGRAM_MIN, _NGRAM_MAX + 1):
        if size > length:
            break
        for start in range(length - size + 1):
            grams.append(text[start : start + size])
    return grams


def _zh_term_ngrams(term: str) -> list[str]:
    """反查命中的中文业务词（如"成交 GMV"）可能夹杂空格或西文字符，只对其中
    连续汉字片段做 2~4 字滑窗切分——不能把整串按字符位置硬切，否则会切出
    "GM"/"MV" 这类混入大写西文字母的伪 token，破坏"全部 token 均为小写"
    这条不变量。"""

    grams: list[str] = []
    for run in _CJK_RUN.finditer(term):
        grams.extend(_cjk_ngrams(run.group()))
    return grams


def _zh_synonyms_for_token(token: str) -> tuple[str, ...]:
    """反查一个英文候选词对应的中文业务词表 key，容忍简单的英文复数形式。

    只做「去掉结尾 s」这一种最简单、确定性的形态归一——不是通用词干提取，
    足以覆盖 "amounts"/"orders" 这类常见复数，命中不了就原样放弃，不引入
    第三方分词或词形还原库。
    """

    terms = zh_business_terms_for_english_word(token)
    if not terms and len(token) > 3 and token.endswith("s"):
        terms = zh_business_terms_for_english_word(token[:-1])
    return terms


def tokenize(question: str) -> tuple[str, ...]:
    """把原始问题切成候选词，全部小写，过滤停用词，不做任何 LLM 调用。

    对通过停用词过滤的英文词，额外反查 `catalog.py` 的中英业务词表，把能
    反查到的中文同义词（同样按 2~4 字滑窗切分）追加进候选词——这样英文问题
    也能命中以中文为主的打分语料，见模块顶部的 Task 5 说明。反查不到的词
    不受影响，仍然只贡献它自己的英文形态。
    """

    tokens: list[str] = []
    for run in _CJK_RUN.finditer(question):
        tokens.extend(_cjk_ngrams(run.group()))
    for match in _ALNUM_TOKEN.finditer(question):
        tokens.append(match.group().lower())

    filtered = [
        token for token in tokens if token not in ZH_STOPWORDS and token not in EN_STOPWORDS
    ]

    synonyms: list[str] = []
    for token in filtered:
        for zh_term in _zh_synonyms_for_token(token):
            synonyms.extend(_zh_term_ngrams(zh_term))

    # dict.fromkeys 去重且保持首次出现顺序，比 set 更利于测试断言与日志复现。
    return tuple(dict.fromkeys([*filtered, *synonyms]))


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
