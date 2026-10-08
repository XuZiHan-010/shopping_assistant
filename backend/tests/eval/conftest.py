"""评测骨架专用夹具与安全门禁零 skip 钩子（Task 2 步骤 4）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from fastapi import FastAPI

    from app.eval.security_harness import SecurityHarness

MERCHANT_ONE_SLUG = "borough-api-100"
MERCHANT_TWO_SLUG = "borough-api-101"

_GATE_FILE = "tests/eval/test_security_gate.py"
_skipped: list[str] = []


def pytest_configure(config: pytest.Config) -> None:
    """在收集及任何 skip 发生前初始化；整个 pytest 会话内不再清空。"""

    del config
    _skipped.clear()


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.skipped and _GATE_FILE in report.nodeid.replace("\\", "/"):
        _skipped.append(report.nodeid)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """安全门禁的任何 skip 都不算「通过」——见 Task 2 步骤 4。"""

    if report.skipped and _GATE_FILE in report.nodeid.replace("\\", "/"):
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session, exitstatus
    if _skipped:
        pytest.exit(
            f"\n安全门禁出现 skip（{len(_skipped)} 条），视同失败：{_skipped[:5]}",
            returncode=pytest.ExitCode.TESTS_FAILED,
        )


@pytest_asyncio.fixture
async def security_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    """带演示顾客绑定能力的真实 PostgreSQL 应用；仅供安全门禁使用。"""

    # 零 skip 钩子的隔离子进程不使用这些夹具，勿在收集阶段加载整个应用及模型依赖。
    from app.core.config import AppEnvironment, Settings
    from app.db.session import Database
    from app.main import create_app
    from app.models.merchant import Merchant
    from tests.conftest import (
        ADMIN_TOKEN,
        MERCHANT_ONE_ID,
        MERCHANT_ONE_TOKEN,
        MERCHANT_TWO_ID,
        MERCHANT_TWO_TOKEN,
    )
    from tests.postgres import truncate_all_tables

    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={
            MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID,
            MERCHANT_TWO_TOKEN: MERCHANT_TWO_ID,
        },
        admin_token=ADMIN_TOKEN,
        rate_limit_per_minute=1000,
        demo_deployment_mode=True,
        demo_customer_identities={
            MERCHANT_ONE_SLUG: "server-resolved-buyer-a",
            MERCHANT_TWO_SLUG: "server-resolved-buyer-b",
        },
    )
    database = Database(settings)
    async with database.session() as session:
        await truncate_all_tables(session)
        session.add_all(
            [
                Merchant(
                    id=MERCHANT_ONE_ID,
                    merchant_code=MERCHANT_ONE_SLUG,
                    display_name="Borough商家100",
                ),
                Merchant(
                    id=MERCHANT_TWO_ID,
                    merchant_code=MERCHANT_TWO_SLUG,
                    display_name="Borough商家101",
                ),
            ]
        )
        await session.commit()

    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest.fixture
def security_harness(security_app: FastAPI) -> SecurityHarness:
    from app.db.session import Database
    from app.eval.security_harness import MerchantFixture, SecurityHarness
    from tests.conftest import (
        MERCHANT_ONE_ID,
        MERCHANT_ONE_TOKEN,
        MERCHANT_TWO_ID,
        MERCHANT_TWO_TOKEN,
    )

    database: Database = security_app.state.database
    return SecurityHarness(
        security_app,
        database,
        merchants={
            "a": MerchantFixture(
                merchant_id=MERCHANT_ONE_ID,
                shop_slug=MERCHANT_ONE_SLUG,
                bearer_token=MERCHANT_ONE_TOKEN,
            ),
            "b": MerchantFixture(
                merchant_id=MERCHANT_TWO_ID,
                shop_slug=MERCHANT_TWO_SLUG,
                bearer_token=MERCHANT_TWO_TOKEN,
            ),
        },
    )
