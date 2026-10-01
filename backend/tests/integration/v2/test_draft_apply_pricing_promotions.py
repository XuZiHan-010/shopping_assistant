"""调价与促销券草稿应用（N3 阶段 C Task 4，PRD M6）——真实 PostgreSQL。

沿用 `test_draft_apply.py` 的播种与断言助手；本文件只覆盖 `PriceChangeHandler`、
`CouponHandler` 特有的行为：护栏预检/复检、目标基数并发校验、券的新建插入路径。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update

from app.db.session import Database
from app.models.analytics import Product
from app.models.drafts import Draft
from app.models.promotion import Coupon, GuardrailConfig
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import AGENT_ACTOR, DRAFT_TTL
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration

DRAFTS_PATH = "/api/v2/merchant/drafts"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _stage_price_change(
    database: Database,
    merchant_id: UUID,
    product_id: UUID,
    *,
    base_price: Decimal,
    new_price: Decimal,
) -> UUID:
    async with database.session() as session:
        draft = Draft(
            merchant_id=merchant_id,
            kind=DraftKind.PRICE_CHANGE.value,
            title=f"调价 → {new_price}",
            target_type="PRODUCT",
            target_id=product_id,
            target_version=int(base_price * 100),
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={
                "base_price": str(base_price),
                "new_price": str(new_price),
                "product_title": "测试商品",
            },
            guardrail_snapshot={"checks": [], "checked_at": datetime.now(UTC).isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=datetime.now(UTC) + DRAFT_TTL,
        )
        session.add(draft)
        await session.commit()
        return draft.id


async def _stage_coupon(
    database: Database,
    merchant_id: UUID,
    *,
    coupon_id: UUID | None = None,
    kind: str = "FULL_REDUCTION",
    discount_rate: Decimal | None = None,
    discount_amount: Decimal | None = Decimal("10.00"),
    threshold_amount: Decimal | None = Decimal("100.00"),
) -> tuple[UUID, UUID]:
    target_id = coupon_id or uuid4()
    async with database.session() as session:
        draft = Draft(
            merchant_id=merchant_id,
            kind=DraftKind.COUPON.value,
            title="促销券：测试满减",
            target_type="COUPON",
            target_id=target_id,
            target_version=0,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={
                "name": "测试券",
                "kind": kind,
                "threshold_amount": str(threshold_amount) if threshold_amount else None,
                "discount_amount": str(discount_amount) if discount_amount else None,
                "discount_rate": str(discount_rate) if discount_rate else None,
                "scope": "ALL",
                "product_ids": [],
                "starts_at": datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
                "ends_at": datetime(2026, 12, 31, tzinfo=UTC).isoformat(),
            },
            guardrail_snapshot={"checks": [], "checked_at": datetime.now(UTC).isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=datetime.now(UTC) + DRAFT_TTL,
        )
        session.add(draft)
        await session.commit()
        return draft.id, target_id


async def _detail(client: AsyncClient, headers: dict[str, str], draft_id: UUID) -> dict[str, Any]:
    resp = await client.get(f"{DRAFTS_PATH}/{draft_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _evidence(client: AsyncClient, headers: dict[str, str], draft_id: UUID) -> str:
    body = await _detail(client, headers, draft_id)
    assert body["approval_evidence"]
    return str(body["approval_evidence"])


async def _apply(
    client: AsyncClient,
    headers: dict[str, str],
    draft_id: UUID,
    *,
    evidence: str,
    target_version: int,
    crid: str = "apply-pricing-1",
) -> Any:
    return await client.post(
        f"{DRAFTS_PATH}/{draft_id}/apply",
        json={
            "client_request_id": crid,
            "draft_version": 1,
            "target_version": target_version,
            "approval_evidence": evidence,
        },
        headers=headers,
    )


async def _price(database: Database, product_id: UUID) -> Decimal:
    async with database.session() as session:
        return Decimal(str((await session.get(Product, product_id)).price))  # type: ignore[union-attr]


async def _set_guardrail(
    database: Database,
    merchant_id: UUID,
    *,
    max_discount_rate: Decimal = Decimal("0.20"),
    max_price_change_rate: Decimal = Decimal("0.30"),
    min_allowed_price: Decimal | None = Decimal("1.00"),
) -> None:
    async with database.session() as session:
        existing = await session.get(GuardrailConfig, merchant_id)
        if existing is None:
            session.add(
                GuardrailConfig(
                    merchant_id=merchant_id,
                    max_discount_rate=max_discount_rate,
                    max_price_change_rate=max_price_change_rate,
                    min_allowed_price=min_allowed_price,
                    max_restock_delta=500,
                    updated_by="test",
                )
            )
        else:
            existing.max_discount_rate = max_discount_rate
            existing.max_price_change_rate = max_price_change_rate
            existing.min_allowed_price = min_allowed_price
        await session.commit()


# --- 调价草稿 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_change_applies_and_updates_product_price(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID, min_allowed_price=Decimal("10.00"))
    product = await seed_product(database, MERCHANT_ONE_ID)
    draft_id = await _stage_price_change(
        database, MERCHANT_ONE_ID, product, base_price=Decimal("100.00"), new_price=Decimal("85.00")
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=10000)
    assert resp.status_code == 200, resp.text
    assert await _price(database, product) == Decimal("85.00")


@pytest.mark.asyncio
async def test_price_change_blocked_when_min_price_unconfigured(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID, min_allowed_price=None)
    product = await seed_product(database, MERCHANT_ONE_ID)
    draft_id = await _stage_price_change(
        database, MERCHANT_ONE_ID, product, base_price=Decimal("100.00"), new_price=Decimal("99.00")
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=10000)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "GUARDRAIL_REJECTED"
    # 拒绝的应用不改价、不消费证据（证据未消费体现在草稿仍是 STAGED，可以重新取证据重试）。
    assert await _price(database, product) == Decimal("100.00")


@pytest.mark.asyncio
async def test_price_change_guardrail_tightened_after_drafting_is_enforced_at_apply(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """起草时护栏允许，应用前护栏被收紧：必须按应用时刻生效的配置复检（D9②）。"""

    database = _database(postgres_app)
    await _set_guardrail(
        database,
        MERCHANT_ONE_ID,
        max_price_change_rate=Decimal("0.50"),
        min_allowed_price=Decimal("1.00"),
    )
    product = await seed_product(database, MERCHANT_ONE_ID)
    draft_id = await _stage_price_change(
        database, MERCHANT_ONE_ID, product, base_price=Decimal("100.00"), new_price=Decimal("60.00")
    )
    # 应用前把幅度上限收紧到 10%：60/100 = 40% 降幅已经超限。
    await _set_guardrail(
        database,
        MERCHANT_ONE_ID,
        max_price_change_rate=Decimal("0.10"),
        min_allowed_price=Decimal("1.00"),
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=10000)
    assert resp.status_code == 422, resp.text
    assert await _price(database, product) == Decimal("100.00")


@pytest.mark.asyncio
async def test_price_change_target_conflict_when_price_moved_concurrently(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID, min_allowed_price=Decimal("1.00"))
    product = await seed_product(database, MERCHANT_ONE_ID)
    draft_id = await _stage_price_change(
        database, MERCHANT_ONE_ID, product, base_price=Decimal("100.00"), new_price=Decimal("90.00")
    )
    async with database.session() as session:
        await session.execute(
            update(Product).where(Product.id == product).values(price=Decimal("70.00"))
        )
        await session.commit()
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=10000)
    assert resp.status_code == 409, resp.text


# --- 促销券草稿 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coupon_creates_new_row_on_apply(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID)
    draft_id, coupon_id = await _stage_coupon(database, MERCHANT_ONE_ID, kind="FULL_REDUCTION")
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=0)
    assert resp.status_code == 200, resp.text
    async with database.session() as session:
        coupon = await session.get(Coupon, coupon_id)
    assert coupon is not None
    assert coupon.state == "ACTIVE"


@pytest.mark.asyncio
async def test_coupon_discount_over_20_percent_rejected(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID, max_discount_rate=Decimal("0.20"))
    draft_id, coupon_id = await _stage_coupon(
        database,
        MERCHANT_ONE_ID,
        kind="DISCOUNT",
        discount_rate=Decimal("0.25"),
        discount_amount=None,
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=0)
    assert resp.status_code == 422, resp.text
    async with database.session() as session:
        assert await session.get(Coupon, coupon_id) is None


@pytest.mark.asyncio
async def test_full_reduction_coupon_over_20_percent_rejected_on_apply(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID, max_discount_rate=Decimal("0.20"))
    draft_id, coupon_id = await _stage_coupon(
        database,
        MERCHANT_ONE_ID,
        kind="FULL_REDUCTION",
        threshold_amount=Decimal("100.00"),
        discount_amount=Decimal("25.00"),
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=0)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "GUARDRAIL_REJECTED"
    async with database.session() as session:
        assert await session.get(Coupon, coupon_id) is None


@pytest.mark.asyncio
async def test_coupon_replay_after_apply_is_a_target_conflict_not_a_duplicate_insert(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """同一份草稿不可能被合法地应用两次（应用后状态已是 APPLIED，路由层会先挡）；

    这里改为直接构造"已应用过的目标 id 再来一次插入"场景，验证处理器自身的
    主键冲突兜底（`IntegrityError` → `VersionConflictError`），不依赖路由层状态机。
    """

    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID)
    _, coupon_id = await _stage_coupon(database, MERCHANT_ONE_ID, kind="FULL_REDUCTION")
    async with database.session() as session:
        session.add(
            Coupon(
                id=coupon_id,
                merchant_id=MERCHANT_ONE_ID,
                name="已存在的券",
                kind="FULL_REDUCTION",
                threshold_amount=Decimal("100.00"),
                discount_amount=Decimal("10.00"),
                discount_rate=None,
                scope="ALL",
                product_ids=[],
                starts_at=datetime(2026, 9, 1, tzinfo=UTC),
                ends_at=datetime(2026, 12, 31, tzinfo=UTC),
                state="ACTIVE",
            )
        )
        await session.commit()
    draft_id, _ = await _stage_coupon(database, MERCHANT_ONE_ID, coupon_id=coupon_id)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(postgres_client, headers, draft_id, evidence=evidence, target_version=0)
    assert resp.status_code == 409, resp.text
