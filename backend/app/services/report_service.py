"""每日经营日报：固定口径、固定建议与商家级幂等物化。"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.analytics.contract import METRIC_SPECS
from app.analytics.dates import business_today
from app.core.errors import (
    DailyReportFeedbackConflictError,
    RequestInProgressError,
)
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale
from app.repositories.analytics import DailyReportSignals
from app.schemas.report import DailyReportMetric, DailyReportResponse

logger = logging.getLogger(__name__)

_METRIC_CODES = (
    "gmv",
    "ordering_user_count",
    "order_count",
    "successful_order_count",
    "return_count",
    "refund_amount",
)
_NO_DATA_SUGGESTIONS = (
    "暂无近 7 日经营数据，建议保持商品供给和客服响应稳定。",
    "可以先补齐商品、保证金和商家资料，提升平台经营基础。",
)


class _AnswerLike(Protocol):
    id: UUID
    processing_status: str
    response_payload: dict[str, object] | None


class _ConversationLike(Protocol):
    id: UUID


class _ConversationsLike(Protocol):
    async def get_answer_by_client_request(
        self, merchant_id: UUID, client_request_id: str
    ) -> _AnswerLike | None: ...

    async def get_or_create_daily_report_conversation(
        self, merchant_id: UUID
    ) -> _ConversationLike: ...

    async def create_processing_answer(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID | None,
        client_request_id: str,
        request_digest: str,
    ) -> _AnswerLike: ...

    async def mark_answer_succeeded(
        self, answer: Any, response_payload: dict[str, Any]
    ) -> None: ...

    async def try_acquire_daily_report_recompute_lock(
        self, merchant_id: UUID, report_date: date
    ) -> bool: ...

    async def get_daily_report_answer_for_update(
        self, merchant_id: UUID, client_request_id: str
    ) -> _AnswerLike | None: ...

    async def answer_has_feedback(self, answer_id: UUID) -> bool: ...

    async def delete_answer(self, answer: Any) -> None: ...


class _AnalyticsLike(Protocol):
    async def daily_report_metrics(
        self, *, merchant_id: UUID, report_date: date
    ) -> dict[str, Decimal | int]: ...

    async def recent_daily_report_signals(
        self, *, merchant_id: UUID, report_date: date
    ) -> DailyReportSignals: ...


class _SessionLike(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class DailyReportService:
    def __init__(
        self,
        session: _SessionLike,
        conversations: _ConversationsLike,
        analytics: _AnalyticsLike,
        *,
        now: Callable[[], datetime] | None = None,
        business_timezone: str,
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._analytics = analytics
        self._now = now or (lambda: datetime.now(UTC))
        self._business_timezone = business_timezone

    async def get_or_create(
        self, merchant_id: UUID, *, locale: SupportedLocale = SupportedLocale.ZH_CN
    ) -> DailyReportResponse:
        report_date = business_today(self._now(), timezone=self._business_timezone) - timedelta(
            days=1
        )
        client_request_id = f"daily-report:{report_date.isoformat()}"
        existing = await self._conversations.get_answer_by_client_request(
            merchant_id, client_request_id
        )
        if existing is not None and existing.processing_status == "SUCCEEDED":
            return _localize_response(_response_from_answer(existing), locale)

        response = await self._build_response(merchant_id, report_date)
        conversation = await self._conversations.get_or_create_daily_report_conversation(
            merchant_id
        )
        try:
            answer = await self._conversations.create_processing_answer(
                merchant_id,
                conversation.id,
                None,
                client_request_id,
                hashlib.sha256(client_request_id.encode("utf-8")).hexdigest(),
            )
            response = response.model_copy(update={"answer_id": answer.id})
            await self._conversations.mark_answer_succeeded(
                answer, response.model_dump(mode="json")
            )
            await self._session.commit()
            return _localize_response(response, locale)
        except IntegrityError as error:
            # 并发首次请求时，数据库唯一约束裁定胜者。失败事务回滚后重读已物化的日报，
            # 而不让同一商家收到一次 500 或重复生成一份日报。
            await self._session.rollback()
            raced = await self._conversations.get_answer_by_client_request(
                merchant_id, client_request_id
            )
            if raced is not None and raced.processing_status == "SUCCEEDED":
                return _localize_response(_response_from_answer(raced), locale)
            if raced is not None:
                raise RequestInProgressError() from error
            raise

    async def recompute(
        self,
        merchant_id: UUID,
        report_date: date,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> DailyReportResponse:
        """受控地替换一个历史日报，普通读取路径不调用本方法。"""

        client_request_id = f"daily-report:{report_date.isoformat()}"
        if not await self._conversations.try_acquire_daily_report_recompute_lock(
            merchant_id, report_date
        ):
            raise RequestInProgressError()

        existing = await self._conversations.get_daily_report_answer_for_update(
            merchant_id, client_request_id
        )
        if existing is not None:
            if await self._conversations.answer_has_feedback(existing.id):
                await self._session.rollback()
                raise DailyReportFeedbackConflictError()
            await self._conversations.delete_answer(existing)

        response = await self._build_response(merchant_id, report_date)
        conversation = await self._conversations.get_or_create_daily_report_conversation(
            merchant_id
        )
        try:
            answer = await self._conversations.create_processing_answer(
                merchant_id,
                conversation.id,
                None,
                client_request_id,
                hashlib.sha256(client_request_id.encode("utf-8")).hexdigest(),
            )
            response = response.model_copy(update={"answer_id": answer.id})
            await self._conversations.mark_answer_succeeded(
                answer, response.model_dump(mode="json")
            )
            await self._session.commit()
            return _localize_response(response, locale)
        except IntegrityError as error:
            await self._session.rollback()
            raise RequestInProgressError() from error

    async def _build_response(self, merchant_id: UUID, report_date: date) -> DailyReportResponse:
        try:
            values = await self._analytics.daily_report_metrics(
                merchant_id=merchant_id, report_date=report_date
            )
            signals = await self._analytics.recent_daily_report_signals(
                merchant_id=merchant_id, report_date=report_date
            )
        except Exception as error:
            logger.warning("daily_report_query_degraded", exc_info=error)
            return DailyReportResponse(
                answer_id=UUID(int=0),
                report_date=report_date,
                metrics=[],
                suggestions=list(_NO_DATA_SUGGESTIONS),
                degraded=True,
                degraded_reason="经营数据暂时不可用，本期日报未生成指标。",
            )

        return DailyReportResponse(
            answer_id=UUID(int=0),
            report_date=report_date,
            metrics=[
                DailyReportMetric(
                    metric_code=code,
                    display_name=METRIC_SPECS[code].label,
                    unit=METRIC_SPECS[code].unit,
                    value=values[code],
                )
                for code in _METRIC_CODES
            ],
            suggestions=list(_suggestions(signals)),
            degraded=False,
            degraded_reason=None,
        )


def _suggestions(signals: DailyReportSignals) -> tuple[str, str]:
    if not signals.has_data:
        return _NO_DATA_SUGGESTIONS
    first = (
        "近 7 日存在退款金额，建议优先查看退货退款明细，定位高频原因并优化发货/售后说明。"
        if signals.refund_amount > 0
        else "近 7 日退款压力较低，可以继续保持履约和售后响应稳定。"
    )
    second = (
        "客服工单相对订单量偏高，建议排查催单、物流和商品说明类问题。"
        if signals.ticket_count > signals.order_count * Decimal("0.2")
        else "建议继续关注 GMV、交易成功订单量和优惠使用效果，挑选转化较好的商品加大运营。"
    )
    return first, second


def _response_from_answer(answer: _AnswerLike) -> DailyReportResponse:
    if answer.response_payload is None:
        raise RuntimeError("日报回答缺少持久化载荷")
    return DailyReportResponse.model_validate(answer.response_payload)


def _localize_response(
    response: DailyReportResponse, locale: SupportedLocale
) -> DailyReportResponse:
    """把物化后的日报（永远以 zh-CN 落库，见 `_build_response()`）渲染成目标
    语言的展示形态，不改动持久化内容——同一份物化结果按请求语言各自渲染，
    不为每种语言各存一份。

    `display_name`/`unit`/`suggestions`/`degraded_reason` 全部是闭集固定文案
    （指标展示名与单位见 `analytics/contract.py`；建议与降级说明见
    `report_service.py` 自身的 `_suggestions()`/`_NO_DATA_SUGGESTIONS`），
    因此全部经 `localize_catalog_value()` 零 LLM 渲染；词典未命中时原样保留，
    不调用大模型（日报端点不接受费用防护参数，也不应该为固定文案产生真实
    调用）。`metric_code`、`value`、`report_date`、`answer_id` 保持不变。
    """

    if locale is SupportedLocale.ZH_CN:
        return response

    metrics = [
        metric.model_copy(
            update={
                "display_name": localize_catalog_value(metric.display_name, locale)
                or metric.display_name,
                "unit": localize_catalog_value(metric.unit, locale) or metric.unit,
            }
        )
        for metric in response.metrics
    ]
    suggestions = [
        localize_catalog_value(suggestion, locale) or suggestion
        for suggestion in response.suggestions
    ]
    degraded_reason = (
        localize_catalog_value(response.degraded_reason, locale) or response.degraded_reason
        if response.degraded_reason
        else response.degraded_reason
    )
    return response.model_copy(
        update={
            "metrics": metrics,
            "suggestions": suggestions,
            "degraded_reason": degraded_reason,
        }
    )
