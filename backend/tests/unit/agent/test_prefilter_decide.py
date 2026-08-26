import pytest

from app.agent.prefilter import decide


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
