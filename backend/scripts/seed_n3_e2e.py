"""S3 一次性库上补齐 N3 S2/S5/S6/S7 浏览器验收资产。"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product
from app.models.knowledge import KnowledgeDocument, MetricDefinition
from tests.support.e2e_n3_app import N3_PROMO_PRODUCT_ID
from tests.support.e2e_s3_app import S3_MERCHANT_ID, S3_PRODUCT_ID, build_settings


async def main() -> None:
    database_url = os.environ["S3_E2E_DATABASE_URL"]
    if not database_url.rstrip("/").endswith("_s3_e2e_test"):
        raise RuntimeError("N3 浏览器验收只允许使用 S3 专用的一次性测试库")
    database = Database(build_settings(database_url))
    now = datetime.now(UTC)
    try:
        async with database.session() as session:
            product = Product(
                id=UUID(N3_PROMO_PRODUCT_ID), merchant_id=S3_MERCHANT_ID,
                business_date=(now - timedelta(days=100)).date(),
                product_code="N3-E2E-P002", title="N3 滞销商品", category="女装",
                price=Decimal("100.00"), status="ONLINE",
                listed_at=now - timedelta(days=100), stock_on_hand=80,
                stock_reserved=0, low_stock_threshold=5,
            )
            session.add(product)
            await session.flush()
            order = Order(
                merchant_id=S3_MERCHANT_ID, business_date=(now - timedelta(days=9)).date(),
                order_no="N3-E2E-O001", buyer_key="n3-e2e-buyer",
                order_status="PAID", total_amount=Decimal("300.00"),
                paid_amount=Decimal("300.00"), placed_at=now - timedelta(days=9),
                paid_at=now - timedelta(days=9), payment_status="PAID",
                fulfillment_status="NOT_SHIPPED", lifecycle_origin="V2",
            )
            session.add(order)
            await session.flush()
            session.add(OrderItem(
                merchant_id=S3_MERCHANT_ID, business_date=order.business_date,
                order_id=order.id, product_id=S3_PRODUCT_ID, quantity=3,
                unit_price=Decimal("100.00"), item_amount=Decimal("300.00"),
                discount_amount=Decimal("0.00"), line_total=Decimal("300.00"),
            ))
            metric = await session.scalar(
                select(MetricDefinition).where(MetricDefinition.metric_code == "net_gmv")
            )
            if metric is None:
                session.add(MetricDefinition(
                    metric_code="net_gmv", display_name="净成交额", unit="元",
                    business_definition="当期毛成交额减去当期退款金额",
                    sql_definition="gross_gmv - refund_amount", source="METRIC_CATALOG",
                    owner="经营分析组", dimensions=["date"], source_database="public",
                    source_table="orders", status="ACTIVE",
                ))
            document = await session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.source_path == "平台规则/after_sale_freight.md"
                )
            )
            if document is None:
                session.add(KnowledgeDocument(
                    category="PLATFORM_RULE", title="售后运费规则",
                    content="退货运费由平台承担，商家不需垫付。", source="wiki",
                    source_path="平台规则/after_sale_freight.md", is_complete=True,
                    status="ACTIVE", source_locale="zh-CN",
                ))
            await session.commit()
    finally:
        await database.dispose()


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
