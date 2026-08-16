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
from app.intent.models import (
    CrossBusinessPlan,
    CrossBusinessPlanType,
    DateRange,
    GeneratedMetricPlan,
    QueryIntent,
)
from app.main import create_app
from app.metrics.catalog import MetricPayload
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
    MetricDefinitionSource,
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
from app.services.visualization_service import VisualizationService

MERCHANT_ID = UUID("00000000-0000-0000-0000-00000000f401")
MERCHANT_TOKEN = "f4-e2e-merchant-token"
MERCHANT_ID_B = UUID("00000000-0000-0000-0000-00000000f402")
MERCHANT_TOKEN_B = "f4-e2e-merchant-token-b"
_DETAIL_TRIGGER = "订单明细"
_RANGE = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 7))
_GENERATED_RANGE = DateRange(start=date(2026, 7, 1), end=date(2026, 7, 7))
_NOW = datetime(2026, 8, 7, tzinfo=UTC)


class DeterministicE2EAnalyticsAgent:
    """仅为浏览器验收固定两条意图，绕开 LLM。"""

    def __init__(self, query_service: SafeQueryService, context: MerchantContext) -> None:
        self._query_service = query_service
        self._context = context

    async def run(self, message: str, session_id: UUID) -> AgentRunResult:
        if "查询订单" in message:
            return await self._cross_business_detail(message, session_id)
        if "按城市" in message:
            return await self._generated_metric(message, session_id, group_by="address_city_name")
        if "按商品" in message:
            return await self._generated_metric(message, session_id, group_by="spu_id")
        if _DETAIL_TRIGGER in message or "最近 20 笔订单" in message:
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
        chart_rows = [
            {"date": str(row["date"]), "gmv": float(str(row["gmv"]))} for row in result.rows
        ]
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
            metric_sql_definition="SUM(orders.paid_amount) WHERE orders.order_status = 'PAID'",
            metric_dimensions=["date"],
            metric_source_database="public",
            metric_source_table="orders",
            metric_report_url=None,
            metric_source=MetricDefinitionSource.METRIC_CATALOG,
            metric_generated=False,
            metric_notice=None,
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
        analysis_requested = "分析" in message
        response = ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=f"{message}：已查询真实演示数据。" if analysis_requested else "",
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
            recommendations=(
                [
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
                ]
                if analysis_requested
                else []
            ),
        )
        return AgentRunResult(response=response, steps=steps, query_result=result)

    async def _cross_business_detail(self, message: str, session_id: UUID) -> AgentRunResult:
        sub_order_no = "F4-E2E-B01" if "F4-E2E-B01" in message else "F4-E2E-001"
        result = await self._query_service.execute(
            self._context,
            QueryIntent(
                answer_mode=AnswerMode.DETAIL,
                category=QuestionCategory.TRADE,
                cross_business_plan=CrossBusinessPlan(
                    plan_type=CrossBusinessPlanType.ORDER_TO_REFUND,
                    sub_order_no=sub_order_no,
                ),
                date_range=_RANGE,
            ),
            now=_NOW,
        )
        steps = [ThinkingStep(label="查询真实经营数据", node="query_data")]
        response = ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=f"{message}：{result.notes[-1] if result.notes else '已查询关联订单数据。'}",
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
            query_plan=QueryPlanSummary(summary="订单关联退款明细"),
            data_rows=result.rows,
            total_rows=result.total_rows,
            truncated=result.truncated,
            export=ExportInfo(id=uuid4(), url="/api/exports/pending", expires_at=_NOW),
            recommendations=_recommendations(),
        )
        return AgentRunResult(response=response, steps=steps, query_result=result)

    async def _generated_metric(
        self, message: str, session_id: UUID, *, group_by: str
    ) -> AgentRunResult:
        plan = GeneratedMetricPlan(name="临时成交指标", unit="元", group_by=group_by)
        result = await self._query_service.execute(
            self._context,
            QueryIntent(
                answer_mode=AnswerMode.METRIC,
                category=QuestionCategory.TRADE,
                generated_metric_plan=plan,
                date_range=_GENERATED_RANGE,
            ),
            now=_NOW,
        )
        steps = [ThinkingStep(label="查询真实经营数据", node="query_data")]
        metric = MetricPayload(
            metric_code="generated_trade_metric",
            display_name=plan.name,
            unit=plan.unit,
            definition="按交易明细的后端固定聚合模板计算。",
            source=MetricDefinitionSource.AI_GENERATED.value,
            owner="待认领",
            status=MetricStatus.UNVERIFIED.value,
            generated=True,
            notice="展示名称和单位由模型提出，聚合口径已由后端固定模板执行，仍需人工确认。",
            sql_definition="由后端受控聚合模板生成，不接受模型提供的 SQL 或公式。",
            dimensions=(group_by,),
            source_database="public",
            source_table="orders",
        )
        visualization = VisualizationService().build(result, metric)
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
            query_plan=QueryPlanSummary(summary="受控临时分组指标"),
            metric_code=metric.metric_code,
            metric_display_name=metric.display_name,
            metric_unit=metric.unit,
            metric_definition=metric.definition,
            metric_sql_definition=metric.sql_definition,
            metric_dimensions=list(metric.dimensions),
            metric_source_database=metric.source_database,
            metric_source_table=metric.source_table,
            metric_report_url=None,
            metric_source=MetricDefinitionSource.AI_GENERATED,
            metric_generated=True,
            metric_notice=metric.notice,
            metric_owner=metric.owner,
            metric_status=MetricStatus.UNVERIFIED,
            data_rows=result.rows,
            total_rows=result.total_rows,
            truncated=result.truncated,
            visualization=visualization,
            recommendations=_recommendations(),
        )
        return AgentRunResult(response=response, steps=steps, query_result=result)


def _recommendations() -> list[Recommendation]:
    return [
        Recommendation(
            title="核对订单状态",
            evidence="查询数据来自隔离 PostgreSQL 演示订单。",
            action="结合活动日期继续复核。",
        ),
        Recommendation(
            title="持续观察趋势",
            evidence="仅统计受控查询范围内的数据。",
            action="缩小日期范围后再次查询。",
        ),
    ]


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
