"""GET /api/exports/{export_id} 的 HTTP 契约测试。

跑在真实 PostgreSQL 上：签名鉴权、过期、跨商家隔离、BOM 和公式注入防护
都只有走真实字节流才能证伪。这条端点刻意不要求 `Authorization`（方案
「签名 URL 自带鉴权」），所以这里不测未认证——测的是签名本身。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.dependencies import _DEV_EXPORT_SIGNING_SECRET
from app.models.analytics import Product
from app.models.answer import Answer
from app.models.conversation import Conversation
from app.repositories.analytics import AnalyticsRepository
from app.repositories.export import ExportRepository
from app.services.export_service import ExportService
from app.services.safe_query import ExportSpec
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID

pytestmark = pytest.mark.asyncio


async def _seed_export(app: FastAPI, *, formula_title: bool = False) -> str:
    """插入一件真实商品并落一条真实导出记录，返回签名下载 URL。"""

    async with app.state.database.session() as session:
        conversation = Conversation(merchant_id=MERCHANT_ONE_ID, title="导出契约测试")
        session.add(conversation)
        await session.flush()
        answer = Answer(
            merchant_id=MERCHANT_ONE_ID,
            conversation_id=conversation.id,
            client_request_id=f"export-api-{uuid4()}",
            request_digest="c" * 64,
            processing_status="SUCCEEDED",
            response_payload={},
        )
        session.add(answer)
        session.add(
            Product(
                merchant_id=MERCHANT_ONE_ID,
                business_date=datetime(2026, 8, 3, tzinfo=UTC).date(),
                product_code="SKU-EXPORT-API",
                title="=1+1" if formula_title else "契约测试商品",
                category="女装",
                price=Decimal("100.00"),
                status="ONLINE",
                listed_at=datetime(2026, 8, 3, 2, tzinfo=UTC),
            )
        )
        await session.flush()

        service = ExportService(
            ExportRepository(session),
            AnalyticsRepository(session),
            signing_secret=_DEV_EXPORT_SIGNING_SECRET,
            ttl_minutes=15,
        )
        info = await service.create(
            merchant_id=MERCHANT_ONE_ID,
            answer_id=answer.id,
            spec=ExportSpec(
                table="products",
                columns=("business_date", "product_code", "title", "category", "price", "status"),
                start=datetime(2026, 8, 1, tzinfo=UTC).date(),
                end=datetime(2026, 8, 5, tzinfo=UTC).date(),
                date_filtered=False,
            ),
        )
        await session.commit()
        return info.url


async def test_download_returns_a_single_bom_prefixed_csv_with_safe_headers(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    url = await _seed_export(postgres_app)

    response = await postgres_client.get(url)

    assert response.status_code == 200
    # 必须只有一段 BOM；ExportService 已经在字符串里拼过一次，路由如果再用
    # utf-8-sig 编码会重复加一段，导出的 CSV 开头会变成两段 BOM。
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert not response.content.startswith(b"\xef\xbb\xbf\xef\xbb\xbf")
    assert b"SKU-EXPORT-API" in response.content
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]


async def test_download_escapes_formula_looking_cells(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    url = await _seed_export(postgres_app, formula_title=True)

    response = await postgres_client.get(url)

    assert response.status_code == 200
    assert b"'=1+1" in response.content
    # 没有加引号前缀的裸公式绝不能出现在响应里。
    assert b",=1+1" not in response.content


async def test_tampered_signature_is_rejected(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    url = await _seed_export(postgres_app)

    response = await postgres_client.get(url.replace("signature=", "signature=tampered"))

    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"


async def test_expired_link_is_rejected_with_410(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    async with postgres_app.state.database.session() as session:
        conversation = Conversation(merchant_id=MERCHANT_ONE_ID, title="导出过期测试")
        session.add(conversation)
        await session.flush()
        answer = Answer(
            merchant_id=MERCHANT_ONE_ID,
            conversation_id=conversation.id,
            client_request_id=f"export-expired-{uuid4()}",
            request_digest="d" * 64,
            processing_status="SUCCEEDED",
            response_payload={},
        )
        session.add(answer)
        await session.flush()

        service = ExportService(
            ExportRepository(session),
            AnalyticsRepository(session),
            signing_secret=_DEV_EXPORT_SIGNING_SECRET,
            ttl_minutes=15,
        )
        already_expired = datetime.now(UTC) - timedelta(minutes=1)
        info = await service.create(
            merchant_id=MERCHANT_ONE_ID,
            answer_id=answer.id,
            spec=ExportSpec(
                table="products",
                columns=("business_date", "product_code", "title", "category", "price", "status"),
                start=datetime(2026, 8, 1, tzinfo=UTC).date(),
                end=datetime(2026, 8, 5, tzinfo=UTC).date(),
                date_filtered=False,
            ),
            now=already_expired - timedelta(minutes=15),
        )
        await session.commit()

    response = await postgres_client.get(info.url)

    assert response.status_code == 410
    assert response.json()["code"] == "EXPORT_LINK_EXPIRED"


async def test_another_merchant_cannot_download_by_swapping_the_merchant_id_param(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    url = await _seed_export(postgres_app)
    stolen_url = url.replace(str(MERCHANT_ONE_ID), str(MERCHANT_TWO_ID))

    response = await postgres_client.get(stolen_url)

    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"


async def test_unknown_export_id_with_a_validly_signed_url_returns_404(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    """签名本身没问题（不是篡改场景），只是这条 id 从没落过库。"""

    async with postgres_app.state.database.session() as session:
        service = ExportService(
            ExportRepository(session),
            AnalyticsRepository(session),
            signing_secret=_DEV_EXPORT_SIGNING_SECRET,
            ttl_minutes=15,
        )
        export_id = uuid4()
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        signature = service._signature(export_id, MERCHANT_ONE_ID, expires_at)

    response = await postgres_client.get(
        f"/api/exports/{export_id}",
        params={
            "merchant_id": str(MERCHANT_ONE_ID),
            "expires_at": int(expires_at.timestamp()),
            "signature": signature,
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_missing_signature_query_param_is_rejected_as_invalid_request(
    postgres_client: AsyncClient,
) -> None:
    response = await postgres_client.get(
        f"/api/exports/{uuid4()}",
        params={"merchant_id": str(MERCHANT_ONE_ID), "expires_at": 0},
    )

    assert response.status_code == 422
