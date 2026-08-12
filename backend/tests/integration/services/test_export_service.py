"""ExportService 对真实 PostgreSQL 的集成验收。

单元测试（`tests/unit/services/test_export_service.py`）用假 Repository 钉住了
签名、过期和公式转义；这里换成真实 `AnalyticsRepository`，验证下载时重新执行的
受控查询确实读到了 Postgres 里的数据、商家隔离在数据库层生效，以及
`docs/backend-development-plan.md`「遗留给 B6 的一处不一致」那条书面裁决
（`ExportSpec` 必须尊重 `DetailSpec.date_filtered`，否则商品明细的导出会和
预览不一致）被正确执行。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ExportLinkExpiredError, MerchantScopeViolationError
from app.models.analytics import Order, Product
from app.models.answer import Answer
from app.models.conversation import Conversation
from app.repositories.analytics import AnalyticsRepository
from app.repositories.export import ExportRepository
from app.services.export_service import ExportService
from app.services.safe_query import ExportSpec

WINDOW_START = date(2026, 8, 1)
WINDOW_END = date(2026, 8, 5)


async def _answer_for_merchant(session: AsyncSession, merchant_id: UUID) -> Answer:
    conversation = Conversation(merchant_id=merchant_id, title="导出集成测试")
    session.add(conversation)
    await session.flush()
    answer = Answer(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        client_request_id=f"export-service-{conversation.id}",
        request_digest="b" * 64,
        processing_status="SUCCEEDED",
        response_payload={},
    )
    session.add(answer)
    await session.flush()
    return answer


async def _order(session: AsyncSession, merchant_id: UUID, order_no: str, day: date) -> None:
    session.add(
        Order(
            merchant_id=merchant_id,
            business_date=day,
            order_no=order_no,
            buyer_key="buyer",
            order_status="COMPLETED",
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            placed_at=datetime(day.year, day.month, day.day, 2, tzinfo=UTC),
            paid_at=datetime(day.year, day.month, day.day, 3, tzinfo=UTC),
        )
    )


async def _product(session: AsyncSession, merchant_id: UUID, code: str, listed: date) -> None:
    session.add(
        Product(
            merchant_id=merchant_id,
            business_date=listed,
            product_code=code,
            title=f"商品-{code}",
            category="女装",
            price=Decimal("100.00"),
            status="ONLINE",
            listed_at=datetime(listed.year, listed.month, listed.day, 2, tzinfo=UTC),
        )
    )


def _service(session: AsyncSession) -> ExportService:
    return ExportService(
        ExportRepository(session),
        AnalyticsRepository(session),
        signing_secret="integration-test-secret",
        ttl_minutes=15,
    )


@pytest.mark.asyncio
async def test_download_replays_the_real_order_rows_within_the_saved_window(
    db_session: AsyncSession,
    merchant_one_id: UUID,
) -> None:
    await _order(db_session, merchant_one_id, "NO-IN-WINDOW", date(2026, 8, 3))
    await _order(db_session, merchant_one_id, "NO-OUT-OF-WINDOW", date(2026, 7, 1))
    answer = await _answer_for_merchant(db_session, merchant_one_id)

    service = _service(db_session)
    now = datetime.now(UTC)
    info = await service.create(
        merchant_id=merchant_one_id,
        answer_id=answer.id,
        spec=ExportSpec(
            table="orders",
            columns=("business_date", "order_no", "order_status", "paid_amount", "placed_at"),
            start=WINDOW_START,
            end=WINDOW_END,
        ),
        now=now,
    )

    csv_data = await service.download_from_url(info.url, now=now + timedelta(minutes=1))

    assert "NO-IN-WINDOW" in csv_data
    assert "NO-OUT-OF-WINDOW" not in csv_data


@pytest.mark.asyncio
async def test_download_never_reads_another_merchants_rows(
    db_session: AsyncSession,
    merchant_one_id: UUID,
    merchant_two_id: UUID,
) -> None:
    await _order(db_session, merchant_two_id, "NO-OTHER-MERCHANT", date(2026, 8, 3))
    answer = await _answer_for_merchant(db_session, merchant_one_id)

    service = _service(db_session)
    now = datetime.now(UTC)
    info = await service.create(
        merchant_id=merchant_one_id,
        answer_id=answer.id,
        spec=ExportSpec(
            table="orders",
            columns=("business_date", "order_no", "order_status", "paid_amount", "placed_at"),
            start=WINDOW_START,
            end=WINDOW_END,
        ),
        now=now,
    )

    csv_data = await service.download_from_url(info.url, now=now + timedelta(minutes=1))

    assert "NO-OTHER-MERCHANT" not in csv_data


@pytest.mark.asyncio
async def test_swapping_the_merchant_id_query_param_invalidates_the_signature(
    db_session: AsyncSession,
    merchant_one_id: UUID,
    merchant_two_id: UUID,
) -> None:
    await _order(db_session, merchant_one_id, "NO-OWNER-ONLY", date(2026, 8, 3))
    answer = await _answer_for_merchant(db_session, merchant_one_id)

    service = _service(db_session)
    now = datetime.now(UTC)
    info = await service.create(
        merchant_id=merchant_one_id,
        answer_id=answer.id,
        spec=ExportSpec(
            table="orders",
            columns=("business_date", "order_no", "order_status", "paid_amount", "placed_at"),
            start=WINDOW_START,
            end=WINDOW_END,
        ),
        now=now,
    )
    stolen_url = info.url.replace(str(merchant_one_id), str(merchant_two_id))

    with pytest.raises(MerchantScopeViolationError):
        await service.download_from_url(stolen_url, now=now + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_link_expires_fifteen_minutes_after_issuance_by_default(
    db_session: AsyncSession,
    merchant_one_id: UUID,
) -> None:
    await _order(db_session, merchant_one_id, "NO-TTL", date(2026, 8, 3))
    answer = await _answer_for_merchant(db_session, merchant_one_id)

    service = ExportService(
        ExportRepository(db_session),
        AnalyticsRepository(db_session),
        signing_secret="integration-test-secret",
        ttl_minutes=15,
    )
    now = datetime.now(UTC)
    info = await service.create(
        merchant_id=merchant_one_id,
        answer_id=answer.id,
        spec=ExportSpec(
            table="orders",
            columns=("business_date", "order_no", "order_status", "paid_amount", "placed_at"),
            start=WINDOW_START,
            end=WINDOW_END,
        ),
        now=now,
    )

    assert info.expires_at == now + timedelta(minutes=15)
    with pytest.raises(ExportLinkExpiredError):
        await service.download_from_url(info.url, now=now + timedelta(minutes=15, seconds=1))


@pytest.mark.asyncio
async def test_products_export_ignores_the_saved_window_like_the_preview_does(
    db_session: AsyncSession,
    merchant_one_id: UUID,
) -> None:
    """`products.business_date` 是上架日，`DetailSpec.date_filtered=False`。

    书面裁决（`docs/backend-development-plan.md`「遗留给 B6 的一处不一致」）
    要求 `ExportSpec` 尊重这条语义，导出才会和用户看到的预览同源——否则一个
    180 天前上架、至今仍在售的商品会从预览里看得到、导出的 CSV 里却凭空消失。
    """

    await _product(db_session, merchant_one_id, "SKU-IN-WINDOW", date(2026, 8, 3))
    await _product(db_session, merchant_one_id, "SKU-LONG-AGO", date(2026, 2, 1))
    answer = await _answer_for_merchant(db_session, merchant_one_id)

    service = _service(db_session)
    now = datetime.now(UTC)
    info = await service.create(
        merchant_id=merchant_one_id,
        answer_id=answer.id,
        spec=ExportSpec(
            table="products",
            columns=("business_date", "product_code", "title", "category", "price", "status"),
            start=WINDOW_START,
            end=WINDOW_END,
            date_filtered=False,
        ),
        now=now,
    )

    csv_data = await service.download_from_url(info.url, now=now + timedelta(minutes=1))

    assert "SKU-IN-WINDOW" in csv_data
    assert "SKU-LONG-AGO" in csv_data
