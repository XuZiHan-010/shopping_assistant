"""拒答响应的契约字段与文案（tasks.md 6.1/6.2/6.3）。"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus


class D:
    def __init__(self, p: str, title: str, c: str) -> None:
        self.source_path = p
        self.title = title
        self.content = c
        self.is_complete = True


class K:
    async def list_active(self) -> list[D]:
        return [D("index/README.md", "退款退货域", "退货 退款")]


class M:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _NoHistory:
    async def has_assistant_message(self, merchant_id: UUID, conversation_id: UUID) -> bool:
        del merchant_id, conversation_id
        return False


async def _rejected_response(question: str = "CNN 和 RNN 的区别是什么") -> object:
    llm = FakeLlmClient(responses=[])
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        session_history=_NoHistory(),
        merchant_id=uuid4(),
    )
    result = await graph.run(question, uuid4())
    return result.response


@pytest.mark.asyncio
async def test_rejection_response_matches_invalid_contract_fields_exactly() -> None:
    response = await _rejected_response()

    assert response.answer_mode is AnswerMode.INVALID
    assert response.degraded is False
    assert response.degraded_reason is None
    assert response.quality_status is QualityStatus.NOT_RUN
    assert response.quality_attempts == 0
    assert response.analysis_sources == [AnalysisSource.NONE]


@pytest.mark.asyncio
async def test_rejection_message_is_non_empty_and_not_worded_as_a_failure() -> None:
    response = await _rejected_response()

    assert response.answer.strip() != ""
    for misleading_word in ("失败", "错误", "降级", "故障"):
        assert misleading_word not in response.answer


@pytest.mark.asyncio
async def test_rejection_response_offers_followup_suggestions() -> None:
    response = await _rejected_response()

    assert len(response.suggestions) > 0


def test_rejection_message_is_registered_in_the_bilingual_catalog() -> None:
    """Task 5：拒答文案必须是 `catalog.py` 能查到译文的"词表键"——按当前请求
    locale 渲染成对应语言由 Task 6 接线，这里只守住这句字面量没有和词典登记项
    悄悄漂移（例如有人改了措辞却忘了同步 catalog.py）。
    """

    from app.agent.graph import _PREFILTER_REJECTION_MESSAGE
    from app.localization.catalog import localize_catalog_value
    from app.localization.locales import SupportedLocale

    assert localize_catalog_value(_PREFILTER_REJECTION_MESSAGE, SupportedLocale.EN_US) is not None
