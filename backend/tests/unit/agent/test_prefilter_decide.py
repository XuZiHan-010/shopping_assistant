from dataclasses import dataclass

import pytest

from app.agent.prefilter import decide
from app.knowledge.retrieval import KnowledgeRetrieval


async def _score(_terms: tuple[str, ...]) -> int:
    return 0


async def _score_high(_terms: tuple[str, ...]) -> int:
    return 10


async def _score_raises(_terms: tuple[str, ...]) -> int:
    raise RuntimeError("语料读取失败")


async def _score_none(_terms: tuple[str, ...]) -> int | None:
    return None


async def _score_records_calls(calls: list[object]) -> int:
    calls.append(True)
    return 0


@pytest.mark.asyncio
async def test_disabled_allows_without_scoring() -> None:
    decision = await decide(
        "CNN 和 RNN 的区别是什么",
        enabled=False,
        min_score=3,
        session_has_prior_turn=False,
        score_question=_score,
    )

    assert decision.allowed is True
    assert decision.reason == "disabled"


@pytest.mark.asyncio
async def test_session_with_prior_turn_allows_without_scoring() -> None:
    decision = await decide(
        "那上个月呢？",
        enabled=True,
        min_score=3,
        session_has_prior_turn=True,
        score_question=_score,
    )

    assert decision.allowed is True
    assert decision.reason == "session_has_history"


@pytest.mark.asyncio
async def test_greeting_allows_without_scoring() -> None:
    decision = await decide(
        "你好",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=_score,
    )

    assert decision.allowed is True
    assert decision.reason == "greeting"


@pytest.mark.asyncio
async def test_score_at_or_above_threshold_allows() -> None:
    decision = await decide(
        "最近 7 天退货量趋势",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=_score_high,
    )

    assert decision.allowed is True
    assert decision.reason == "score"
    assert decision.score == 10


@pytest.mark.asyncio
async def test_score_below_threshold_rejects() -> None:
    decision = await decide(
        "CNN 和 RNN 的区别是什么",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=_score,
    )

    assert decision.allowed is False
    assert decision.reason == "below_threshold"
    assert decision.score == 0
    assert decision.threshold == 3


@pytest.mark.asyncio
async def test_scoring_failure_fails_open() -> None:
    """语料读取失败时必须放行，不得因为闸门自身故障拒绝用户（design.md D4）。"""

    decision = await decide(
        "CNN 和 RNN 的区别是什么",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=_score_raises,
    )

    assert decision.allowed is True
    assert decision.reason == "corpus_unavailable"


@pytest.mark.asyncio
async def test_corpus_entirely_unavailable_fails_open() -> None:
    """`None`（语料完全不可用）与 0 分（语料存在但没命中）走不同分支：
    前者必须放行，后者必须拒绝——见 `KnowledgeRetrieval.score_question` 的区分。
    """

    decision = await decide(
        "CNN 和 RNN 的区别是什么",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=_score_none,
    )

    assert decision.allowed is True
    assert decision.reason == "corpus_unavailable"


@pytest.mark.asyncio
async def test_disabled_short_circuits_before_calling_scorer() -> None:
    calls: list[object] = []

    await decide(
        "任意问题",
        enabled=False,
        min_score=3,
        session_has_prior_turn=False,
        score_question=lambda terms: _score_records_calls(calls),
    )

    assert calls == []


# ---------------------------------------------------------------------------
# Task 5：闸门升级为双语——语料仍然是纯中文（知识文档标题、正式指标目录都是
# 中文），验证英文提问不会因此被误拒，也验证真正范围外的英文提问依然会被拒。
# ---------------------------------------------------------------------------


@dataclass
class _Doc:
    source_path: str
    title: str
    content: str
    is_complete: bool = True


@dataclass
class _Metric:
    metric_code: str
    display_name: str


class _KnowledgeRepo:
    def __init__(self, documents: list[_Doc]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_Doc]:
        return self._documents


class _MetricRepo:
    def __init__(self, metrics: list[_Metric]) -> None:
        self._metrics = metrics

    async def list_active(self) -> list[_Metric]:
        return self._metrics


@pytest.fixture
def chinese_corpus() -> KnowledgeRetrieval:
    """全中文语料：知识文档标题与正式指标目录都不含任何英文词——真实生产环境
    下知识库以中文为主，任何"魔改语料本身让它认识英文"的抄近道在这里都行不通，
    只有 `prefilter.tokenize()` 的双语同义词反查才能让英文提问命中它。
    """

    return KnowledgeRetrieval(
        _KnowledgeRepo([_Doc("业务/交易/退款流程.md", "退款退货域", "退款金额与退款量说明")]),
        metrics=_MetricRepo(
            [
                _Metric("refund_amount", "退款金额"),
                _Metric("refund_count", "退款量"),
            ]
        ),
    )


@pytest.mark.asyncio
async def test_prefilter_scores_english_business_question(chinese_corpus) -> None:
    """英文正当经营提问不得因为打分语料是中文就被判范围外。"""

    decision = await decide(
        "What are the refund amounts for the last 7 days?",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=chinese_corpus.score_question,
    )

    assert decision.allowed is True
    assert decision.reason == "score"


@pytest.mark.asyncio
async def test_prefilter_still_rejects_an_english_out_of_scope_question(chinese_corpus) -> None:
    """双语同义词扩展只补业务词，不能让闸门变得来者不拒——真正范围外的英文
    问题（不含任何可反查的经营词汇）仍然要被拒绝。
    """

    decision = await decide(
        "What is the weather like today?",
        enabled=True,
        min_score=3,
        session_has_prior_turn=False,
        score_question=chinese_corpus.score_question,
    )

    assert decision.allowed is False
    assert decision.reason == "below_threshold"
