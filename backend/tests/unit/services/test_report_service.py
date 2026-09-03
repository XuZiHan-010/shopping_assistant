"""日报服务的日期、建议和可见降级行为。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.localization.locales import SupportedLocale
from app.repositories.analytics import DailyReportSignals
from app.services.report_service import DailyReportService

MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000001a1")


class _Conversations:
    def __init__(self) -> None:
        self.answer = None
        self.saved_payload: dict[str, object] | None = None

    async def get_answer_by_client_request(self, merchant_id: UUID, client_request_id: str):
        assert merchant_id == MERCHANT_ID
        assert client_request_id == "daily-report:2026-08-20"
        return self.answer

    async def get_or_create_daily_report_conversation(self, merchant_id: UUID):
        assert merchant_id == MERCHANT_ID
        return SimpleNamespace(id=uuid4())

    async def create_processing_answer(self, *args, **kwargs):
        return SimpleNamespace(id=uuid4())

    async def mark_answer_succeeded(self, answer, response_payload: dict[str, object]) -> None:
        self.saved_payload = response_payload
        answer.response_payload = response_payload


class _Session:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _Analytics:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def daily_report_metrics(self, *, merchant_id: UUID, report_date):
        assert merchant_id == MERCHANT_ID
        assert str(report_date) == "2026-08-20"
        if self.fail:
            raise RuntimeError("数据库暂不可用")
        return {
            "gmv": Decimal("200.00"),
            "ordering_user_count": 2,
            "order_count": 4,
            "successful_order_count": 3,
            "return_count": 1,
            "refund_amount": Decimal("20.00"),
        }

    async def recent_daily_report_signals(self, *, merchant_id: UUID, report_date):
        assert merchant_id == MERCHANT_ID
        assert str(report_date) == "2026-08-20"
        return DailyReportSignals(
            has_data=True,
            refund_amount=Decimal("20.00"),
            order_count=4,
            ticket_count=1,
        )


@pytest.mark.asyncio
async def test_report_uses_business_yesterday_and_refund_suggestion() -> None:
    conversations = _Conversations()
    service = DailyReportService(
        _Session(),
        conversations,
        _Analytics(),
        now=lambda: datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
        business_timezone="Asia/Shanghai",
    )

    report = await service.get_or_create(MERCHANT_ID)

    assert str(report.report_date) == "2026-08-20"
    assert [metric.metric_code for metric in report.metrics] == [
        "gmv",
        "ordering_user_count",
        "order_count",
        "successful_order_count",
        "return_count",
        "refund_amount",
    ]
    assert report.metrics[0].value == Decimal("200.00")
    assert len(report.suggestions) == 2
    assert "退款金额" in report.suggestions[0]
    assert report.degraded is False
    assert conversations.saved_payload is not None


@pytest.mark.asyncio
async def test_report_renders_english_labels_and_suggestions_without_changing_the_cache() -> None:
    """Task 8：`get_or_create()` 传 `locale=en-US` 时,展示名/单位/建议按
    `app.localization.catalog` 渲染成英文，但落库的 `saved_payload`
    （`mark_answer_succeeded()` 收到的载荷）必须是 zh-CN 原文——物化结果永远
    以 zh-CN 落库，locale 只影响这次请求的返回值，不影响下一次请求缓存命中
    后按别的 locale 渲染的能力。"""

    conversations = _Conversations()
    service = DailyReportService(
        _Session(),
        conversations,
        _Analytics(),
        now=lambda: datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
        business_timezone="Asia/Shanghai",
    )

    report = await service.get_or_create(MERCHANT_ID, locale=SupportedLocale.EN_US)

    gmv_metric = next(metric for metric in report.metrics if metric.metric_code == "gmv")
    assert gmv_metric.display_name == "Transaction GMV"
    assert gmv_metric.unit == "yuan"
    assert gmv_metric.value == Decimal("200.00")
    assert "refund" in report.suggestions[0].lower()
    assert "退款" not in report.suggestions[0]

    assert conversations.saved_payload is not None
    saved_metrics = {item["metric_code"]: item for item in conversations.saved_payload["metrics"]}
    assert saved_metrics["gmv"]["display_name"] == "成交 GMV"
    assert saved_metrics["gmv"]["unit"] == "元"
    assert "退款金额" in conversations.saved_payload["suggestions"][0]


@pytest.mark.asyncio
async def test_report_cache_hit_still_renders_the_requested_locale() -> None:
    """第二次请求命中已物化的日报（`existing.processing_status == "SUCCEEDED"`）
    时，仍必须按这次请求的 `locale` 渲染，而不是原样返回第一次请求存下来的
    语言。"""

    conversations = _Conversations()
    service = DailyReportService(
        _Session(),
        conversations,
        _Analytics(),
        now=lambda: datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
        business_timezone="Asia/Shanghai",
    )
    first = await service.get_or_create(MERCHANT_ID)
    conversations.answer = SimpleNamespace(
        id=first.answer_id,
        processing_status="SUCCEEDED",
        response_payload=first.model_dump(mode="json"),
    )

    second = await service.get_or_create(MERCHANT_ID, locale=SupportedLocale.EN_US)

    assert second.answer_id == first.answer_id
    gmv_metric = next(metric for metric in second.metrics if metric.metric_code == "gmv")
    assert gmv_metric.display_name == "Transaction GMV"


@pytest.mark.asyncio
async def test_report_exposes_query_failure_without_zero_metrics() -> None:
    service = DailyReportService(
        _Session(),
        _Conversations(),
        _Analytics(fail=True),
        now=lambda: datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
        business_timezone="Asia/Shanghai",
    )

    report = await service.get_or_create(MERCHANT_ID)

    assert report.metrics == []
    assert report.degraded is True
    assert report.degraded_reason
    assert len(report.suggestions) == 2
