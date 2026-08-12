"""F4 浏览器验收的确定性后端入口。

只固定意图选择；经营数据、商家隔离与签名 CSV 仍走 B7 的真实服务，
因此浏览器验收不产生 LLM 调用或费用。
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import AgentRunResult
from app.api.dependencies import (
    get_app_settings,
    get_chat_service,
    get_database,
    get_db_session,
    get_merchant_context,
)
from app.core.config import AppEnvironment, Settings
from app.core.security import MerchantContext
from app.db.session import Database
from app.intent.models import DateRange, QueryIntent
from app.main import create_app
from app.repositories.analytics import AnalyticsRepository
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.export import ExportRepository
from app.schemas.chat import (
    AnalysisSource,
    AnswerMode,
    ChartType,
    ChatResponse,
    ExportInfo,
    MetricStatus,
    QualityStatus,
    QueryPlanSummary,
    QuestionCategory,
    Recommendation,
    ThinkingStep,
    Visualization,
)
from app.services.chat_service import ChatService
from app.services.export_service import ExportService
from app.services.merchant_scope import MerchantScopeService
from app.services.safe_query import SafeQueryService

MERCHANT_ID = UUID("00000000-0000-0000-0000-00000000f401")
MERCHANT_TOKEN = "f4-e2e-merchant-token"
MERCHANT_ID_B = UUID("00000000-0000-0000-0000-00000000f402")
MERCHANT_TOKEN_B = "f4-e2e-merchant-token-b"
_DETAIL_TRIGGER = "订单明细"
_RANGE = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 7))
_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class DeterministicE2EAnalyticsAgent:
    """仅为浏览器验收固定两条意图，绕开 LLM。"""

    def __init__(self, query_service: SafeQueryService, context: MerchantContext) -> None:
        self._query_service = query_service
        self._context = context

    async def run(self, message: str, session_id: UUID) -> AgentRunResult:
        if _DETAIL_TRIGGER in message:
            return await self._detail(message, session_id)
        return await self._metric(message, session_id)

    async def _metric(self, message: str, session_id: UUID) -> AgentRunResult:
        result = await self._query_service.execute(
            self._context,
            QueryIntent(
                answer_mode=AnswerMode.METRIC,
                category=QuestionCategory.TRADE,
                metric="gmv",
                dimensions=["date"],
                date_range=_RANGE,
            ),
            now=_NOW,
        )
        steps = [ThinkingStep(label="查询真实经营数据", node="query_data")]
        chart_rows = [{"date": str(row["date"]), "gmv": float(row["gmv"])} for row in result.rows]
        response = ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=f"{message}：已查询真实演示数据。",
            answer_mode=AnswerMode.METRIC,
            category=QuestionCategory.TRADE,
            thinking_steps=steps,
            quality_status=QualityStatus.NOT_RUN,
            quality_attempts=0,
            quality_notes=["浏览器验收使用确定性意图解析，不调用 LLM。"],
            analysis_sources=[AnalysisSource.DATABASE],
            degraded=False,
            degraded_reason=None,
            suggestions=["查看订单明细"],
            suggestion_alternates=[],
            query_plan=QueryPlanSummary(summary="GMV 日趋势：2026-08-01 至 2026-08-07"),
            metric_code="gmv",
            metric_display_name="成交 GMV",
            metric_unit="元",
            metric_definition="已支付订单金额之和。",
            metric_source="F4 浏览器验收演示数据",
            metric_owner="Borough",
            metric_status=MetricStatus.ACTIVE,
            data_rows=result.rows,
            total_rows=result.total_rows,
            truncated=result.truncated,
            visualization=Visualization(
                enabled=True,
                type=ChartType.LINE,
                allowed_types=[ChartType.LINE],
                title="成交 GMV 趋势",
                dimension_key="date",
                metric_key="gmv",
                unit="元",
                data=chart_rows,
            ),
            recommendations=[
                Recommendation(
                    title="关注成交变化",
                    evidence="图表数据来自隔离 PostgreSQL 演示订单。",
                    action="结合活动日期继续复核。",
                ),
                Recommendation(
                    title="持续观察趋势",
                    evidence="仅统计已支付订单。",
                    action="缩小日期范围后再次查询。",
                ),
            ],
        )
        return AgentRunResult(response=response, steps=steps, query_result=result)

    async def _detail(self, message: str, session_id: UUID) -> AgentRunResult:
        result = await self._query_service.execute(
            self._context,
            QueryIntent(
                answer_mode=AnswerMode.DETAIL,
                category=QuestionCategory.TRADE,
                date_range=_RANGE,
                limit=50,
            ),
            now=_NOW,
        )
        steps = [ThinkingStep(label="查询真实经营数据", node="query_data")]
        response = ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=f"{message}：已查询真实演示数据。",
            answer_mode=AnswerMode.DETAIL,
            category=QuestionCategory.TRADE,
            thinking_steps=steps,
            quality_status=QualityStatus.NOT_RUN,
            quality_attempts=0,
            quality_notes=["浏览器验收使用确定性意图解析，不调用 LLM。"],
            analysis_sources=[AnalysisSource.DATABASE],
            degraded=False,
            degraded_reason=None,
            suggestions=["查看 GMV 趋势"],
            suggestion_alternates=[],
            query_plan=QueryPlanSummary(summary="订单明细：2026-08-01 至 2026-08-07"),
            data_rows=result.rows,
            total_rows=result.total_rows,
            truncated=result.truncated,
            export=ExportInfo(id=uuid4(), url="/api/exports/pending", expires_at=_NOW),
            recommendations=[
                Recommendation(
                    title="核对订单状态",
                    evidence=f"当前返回 {result.total_rows} 条订单明细。",
                    action="下载 CSV 后按订单状态和金额进行复核。",
                ),
                Recommendation(
                    title="关注截断提示",
                    evidence=(
                        "明细已按安全上限截断。" if result.truncated else "当前结果未触发截断。"
                    ),
                    action="缩短日期范围以查看更聚焦的订单明细。",
                ),
            ],
        )
        return AgentRunResult(response=response, steps=steps, query_result=result)


def get_e2e_chat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
) -> ChatService:
    conversations = ConversationRepository(session)
    analytics = AnalyticsRepository(session)
    return ChatService(
        session,
        conversations,
        DeterministicE2EAnalyticsAgent(
            SafeQueryService(analytics, business_timezone=settings.business_timezone), context
        ),
        MerchantScopeService(conversations, AuditRepository(database)),
        ExportService(
            ExportRepository(session),
            analytics,
            signing_secret=settings.export_signing_secret or "f4-e2e-export-secret",
            ttl_minutes=settings.export_url_ttl_minutes,
        ),
    )


def build_e2e_app(database_url: str) -> object:
    app = create_app(
        Settings(
            app_env=AppEnvironment.TEST,
            database_url=database_url,
            frontend_origin="http://127.0.0.1:5274",
            demo_merchant_tokens={
                MERCHANT_TOKEN: MERCHANT_ID,
                MERCHANT_TOKEN_B: MERCHANT_ID_B,
            },
            admin_token="f4-e2e-admin-token",
            export_signing_secret="f4-e2e-export-secret",
        )
    )
    app.dependency_overrides[get_chat_service] = get_e2e_chat_service
    return app


app = build_e2e_app(os.environ["F4_E2E_DATABASE_URL"])
