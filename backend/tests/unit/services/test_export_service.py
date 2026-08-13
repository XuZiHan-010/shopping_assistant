from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.analytics.contract import DETAIL_SPECS
from app.core.errors import AppError, ErrorCode, ResourceNotFoundError
from app.intent.models import CrossBusinessPlan, CrossBusinessPlanType, GeneratedMetricPlan
from app.repositories.analytics import DetailResult, ResultColumn
from app.schemas.chat import QuestionCategory
from app.services.export_service import ExportService
from app.services.safe_query import ExportSpec


@dataclass
class _Record:
    id: UUID
    merchant_id: UUID
    answer_id: UUID
    export_spec: dict[str, object]
    expires_at: datetime


class _Exports:
    def __init__(self) -> None:
        self.record: _Record | None = None

    async def create(self, **kwargs: object) -> _Record:
        self.record = _Record(id=uuid4(), **kwargs)  # type: ignore[arg-type]
        return self.record

    async def get_for_signed_download(self, export_id: UUID, merchant_id: UUID) -> _Record | None:
        if self.record and self.record.id == export_id and self.record.merchant_id == merchant_id:
            return self.record
        return None


class _Analytics:
    def __init__(self) -> None:
        self.generated_metric_calls: list[dict[str, object]] = []

    async def export_detail(self, **kwargs: object) -> DetailResult:
        return DetailResult(
            columns=(ResultColumn("order_no", "订单号", "DIMENSION"),),
            rows=[{"order_no": "=formula"}],
            total_rows=1,
            truncated=False,
            source_tables=("orders",),
        )

    async def export_cross_business(self, **kwargs: object) -> DetailResult:
        return DetailResult(
            columns=(ResultColumn("order_no", "订单号", "DIMENSION"),),
            rows=[{"order_no": "NO-CROSS-1"}],
            total_rows=1,
            truncated=False,
            source_tables=("orders", "order_items", "products"),
        )

    async def generated_metric(self, **kwargs: object) -> DetailResult:
        self.generated_metric_calls.append(kwargs)
        return DetailResult(
            columns=(
                ResultColumn("spu_id", "SPU ID", "DIMENSION"),
                ResultColumn("spu_name", "SPU 名称", "DIMENSION"),
                ResultColumn("order_count", "成交订单数", "METRIC"),
                ResultColumn("order_user_count", "成交用户数", "METRIC"),
                ResultColumn("quantity", "成交件数", "METRIC"),
                ResultColumn("paid_amount", "成交金额", "METRIC"),
            ),
            rows=[
                {
                    "spu_id": "SPU-1",
                    "spu_name": "商品 1",
                    "order_count": 1,
                    "order_user_count": 1,
                    "quantity": 2,
                    "paid_amount": 100,
                }
            ],
            total_rows=1,
            truncated=False,
            source_tables=("orders", "order_items", "products"),
        )


@pytest.mark.asyncio
async def test_signed_export_replays_only_saved_whitelist_spec_and_escapes_csv_formula() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    exports = _Exports()
    merchant_id, answer_id = uuid4(), uuid4()
    service = ExportService(exports, _Analytics(), signing_secret="test-secret", ttl_minutes=15)
    info = await service.create(
        merchant_id=merchant_id,
        answer_id=answer_id,
        spec=ExportSpec(
            table="orders",
            columns=("business_date", "order_no", "order_status", "paid_amount", "placed_at"),
            start=date(2026, 8, 1),
            end=date(2026, 8, 5),
            filters=(("order_status", "PAID"),),
        ),
        now=now,
    )

    assert "signature=" in info.url
    csv_data = await service.download_from_url(info.url, now=now + timedelta(minutes=1))
    assert csv_data.startswith("\ufeff订单号\r\n")
    assert "'=formula" in csv_data


@pytest.mark.asyncio
async def test_tampered_or_expired_export_link_is_not_downloadable() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    exports = _Exports()
    service = ExportService(exports, _Analytics(), signing_secret="test-secret", ttl_minutes=1)
    info = await service.create(
        merchant_id=uuid4(),
        answer_id=uuid4(),
        spec=ExportSpec(
            "orders",
            tuple(name for name, _ in DETAIL_SPECS["orders"].columns),
            date(2026, 8, 1),
            date(2026, 8, 5),
        ),
        now=now,
    )

    with pytest.raises(AppError) as tampered:
        await service.download_from_url(info.url.replace("signature=", "signature=x"), now=now)
    assert tampered.value.code is ErrorCode.MERCHANT_SCOPE_VIOLATION

    with pytest.raises(AppError) as expired:
        await service.download_from_url(info.url, now=now + timedelta(minutes=2))
    assert expired.value.status_code == 410


@pytest.mark.asyncio
async def test_cross_business_export_replays_only_the_saved_fixed_plan() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    exports = _Exports()
    service = ExportService(exports, _Analytics(), signing_secret="test-secret", ttl_minutes=15)
    info = await service.create(
        merchant_id=uuid4(),
        answer_id=uuid4(),
        spec=ExportSpec(
            table="cross_business",
            columns=("order_no",),
            start=date(2026, 8, 1),
            end=date(2026, 8, 5),
            date_filtered=False,
            kind="cross_business",
            cross_business_plan=CrossBusinessPlan(
                plan_type=CrossBusinessPlanType.ORDER_TO_GOODS,
                sub_order_no="NO-CROSS-1",
            ),
        ),
        now=now,
    )

    csv_data = await service.download_from_url(info.url, now=now + timedelta(minutes=1))

    assert "NO-CROSS-1" in csv_data


@pytest.mark.asyncio
async def test_generated_metric_export_replays_the_saved_category_and_plan() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    exports = _Exports()
    analytics = _Analytics()
    merchant_id = uuid4()
    service = ExportService(exports, analytics, signing_secret="test-secret", ttl_minutes=15)
    info = await service.create(
        merchant_id=merchant_id,
        answer_id=uuid4(),
        spec=ExportSpec(
            table="generated_metric",
            columns=(
                "spu_id",
                "spu_name",
                "order_count",
                "order_user_count",
                "quantity",
                "paid_amount",
            ),
            start=date(2026, 8, 1),
            end=date(2026, 8, 5),
            kind="generated_metric",
            generated_metric_plan=GeneratedMetricPlan(
                name="按 SPU 看成交表现",
                unit="元",
                group_by="spu_id",
            ),
            generated_metric_category=QuestionCategory.TRADE,
        ),
        now=now,
    )

    csv_data = await service.download_from_url(info.url, now=now + timedelta(minutes=1))

    assert "SPU-1" in csv_data
    assert analytics.generated_metric_calls[0]["category"] is QuestionCategory.TRADE
    assert analytics.generated_metric_calls[0]["plan"].group_by == "spu_id"


@pytest.mark.asyncio
async def test_tampered_generated_metric_export_spec_is_refused() -> None:
    now = datetime(2026, 8, 5, tzinfo=UTC)
    exports = _Exports()
    service = ExportService(exports, _Analytics(), signing_secret="test-secret", ttl_minutes=15)
    info = await service.create(
        merchant_id=uuid4(),
        answer_id=uuid4(),
        spec=ExportSpec(
            table="generated_metric",
            columns=("spu_id",),
            start=date(2026, 8, 1),
            end=date(2026, 8, 5),
            kind="generated_metric",
            generated_metric_plan=GeneratedMetricPlan(
                name="按 SPU 看成交表现",
                unit="元",
                group_by="spu_id",
            ),
            generated_metric_category=QuestionCategory.TRADE,
        ),
        now=now,
    )
    assert exports.record is not None
    exports.record.export_spec["generated_metric_category"] = "SCM"

    with pytest.raises(ResourceNotFoundError):
        await service.download_from_url(info.url, now=now + timedelta(minutes=1))
