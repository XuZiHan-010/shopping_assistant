"""日报服务的日期、建议和可见降级行为。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

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
