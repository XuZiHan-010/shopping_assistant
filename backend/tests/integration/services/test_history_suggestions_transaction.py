"""历史推荐查询失败不得污染 ChatService 的持久化事务。"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import MerchantQaGraph
from app.core.security import MerchantContext
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.models.answer import Answer
from app.models.conversation import Message
from app.models.merchant import Merchant
from app.repositories.answer import AnswerRepository
from app.repositories.conversation import ConversationRepository
from app.schemas.chat import AnswerMode, ChatRequest, QuestionCategory
from app.services.chat_service import ChatService
from app.services.suggested_questions import suggestions_for

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000051")
CONTEXT = MerchantContext(merchant_id=MERCHANT_ID)


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _NoMetric:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _InvalidLimitHistory:
    """通过真实 PostgreSQL 的负 LIMIT 错误模拟历史查询失效。"""

    def __init__(self, answers: AnswerRepository) -> None:
        self._answers = answers

    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]:
        return await self._answers.top_category_questions(
            merchant_id=merchant_id,
            category=category,
            limit=-1,
        )


def _graph(history_questions: _InvalidLimitHistory) -> MerchantQaGraph:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": [],
                    "filters": {},
                    "date_range": None,
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        merchant_id=MERCHANT_ID,
        history_questions=history_questions,
    )


@pytest.mark.asyncio
async def test_history_query_failure_does_not_abort_main_answer_persistence(
    db_session: AsyncSession,
) -> None:
    """可选历史查询报错后，主回答仍必须在同一会话成功落库。

    删除历史查询的 savepoint 会让 PostgreSQL 把事务标记为 aborted：图节点虽捕获
    `LIMIT -1` 的错误，ChatService 随后的助手消息和 Answer 更新仍会报
    `InFailedSQLTransaction`。本断言锁住事务边界，而非仅断言异常被吞掉。
    """

    db_session.add(
        Merchant(
            id=MERCHANT_ID,
            merchant_code="history-transaction-merchant",
            display_name="历史事务商家",
        )
    )
    await db_session.commit()

    graph = _graph(_InvalidLimitHistory(AnswerRepository(db_session)))
    service = ChatService(db_session, ConversationRepository(db_session), graph)

    execution = await service.submit(
        CONTEXT,
        ChatRequest(message="昨天 GMV", client_request_id="history-query-error"),
        request_id="history-query-error-request",
    )

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert execution.response.suggestions == expected.current
    answers = list(await db_session.scalars(select(Answer)))
    assert len(answers) == 1
    assert answers[0].processing_status == "SUCCEEDED"
    assert answers[0].response_payload is not None
    messages = list(await db_session.scalars(select(Message).order_by(Message.created_at)))
    assert [message.role for message in messages] == ["USER", "ASSISTANT"]
