"""写入 S1 浏览器验收所需的隔离数据（`n2-shop-nextjs-app` Task 8）。

一家店、两款围巾：羊毛款没有填「材质」，羊绒款材质为 100% 羊绒、价格 259 元。
每次运行先清空整库再播种，所以只允许连接专用的 `*_s1_e2e_test` 库。
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.localization.locales import hash_source_text
from app.models.analytics import Product
from app.models.localization import MachineTranslationCache
from app.models.merchant import Merchant
from app.prompts.localization import LOCALIZATION_PROMPT_VERSION
from tests.postgres import TRUNCATE_ALL_TABLES
from tests.support.e2e_s1_app import (
    S1_CASHMERE_ID,
    S1_MERCHANT_ID,
    S1_SHOP_SLUG,
    S1_WOOL_ID,
    build_settings,
)


async def main() -> None:
    database_url = os.environ["S1_E2E_DATABASE_URL"]
    if not database_url.rstrip("/").endswith("_s1_e2e_test"):
        raise RuntimeError("S1 浏览器验收会清空整库，只能连接名称以 _s1_e2e_test 结尾的数据库")

    database = Database(build_settings(database_url))
    listed_at = datetime.now(UTC) - timedelta(days=400)
    try:
        async with database.session() as session:
            await session.execute(text(TRUNCATE_ALL_TABLES))
            session.add(
                Merchant(
                    id=S1_MERCHANT_ID,
                    merchant_code=S1_SHOP_SLUG,
                    display_name="Borough商家100",
                )
            )
            await session.flush()
            for product_id, code, title, price, on_hand, attributes in (
                (S1_WOOL_ID, "S1-E2E-P001", "羊毛围巾", Decimal("129.00"), 30, {}),
                (
                    S1_CASHMERE_ID,
                    "S1-E2E-P002",
                    "羊绒围巾",
                    Decimal("259.00"),
                    12,
                    {"材质": {"value": "100% 羊绒", "source": "MERCHANT"}},
                ),
            ):
                session.add(
                    Product(
                        id=product_id,
                        merchant_id=S1_MERCHANT_ID,
                        business_date=listed_at.date(),
                        product_code=code,
                        title=title,
                        category="围巾",
                        price=price,
                        status="ONLINE",
                        listed_at=listed_at,
                        short_description=f"{title}，冬季保暖",
                        detail_description=f"{title}的详细介绍。",
                        # 使用正式演示目录中的羊绒围巾图片，让 WS 首页 E2E 覆盖真实静态图片加载。
                        image_url="/demo/products/17.webp" if code == "S1-E2E-P002" else None,
                        attributes=attributes,
                        stock_on_hand=on_hand,
                        stock_reserved=0,
                        low_stock_threshold=5,
                    )
                )
            # 固定英文目录译文只供一次性 S1/WS 浏览器库使用；公开 GET 不触发真实模型。
            for source, translated in (
                ("羊毛围巾", "Wool scarf"),
                ("羊绒围巾", "Cashmere scarf"),
            ):
                session.add(
                    MachineTranslationCache(
                        scope_kind="MERCHANT",
                        merchant_id=S1_MERCHANT_ID,
                        source_hash=hash_source_text(source),
                        source_language="zh-CN",
                        target_locale="en-US",
                        translated_text=translated,
                        model="scripted-e2e-fixture",
                        prompt_version=LOCALIZATION_PROMPT_VERSION,
                    )
                )
            await session.commit()
    finally:
        await database.dispose()


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
