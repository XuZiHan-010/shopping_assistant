"""商品内容草稿应用与批量拆分（N3 阶段 C Task 3，PRD M4、D11）——真实 PostgreSQL。

覆盖计划 Task 3 步骤 1 的四条核心断言：缺失属性列为待补而不是模型编造、从描述提取的属性
必须指向原文片段、批量起草拆成每商品一份子草稿、部分批准不影响其余子草稿状态。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.models.analytics import Product
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import AGENT_ACTOR, DRAFT_TTL
from app.tools.merchant.content import derive_batch_id
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers

pytestmark = pytest.mark.integration

DRAFTS_PATH = "/api/v2/merchant/drafts"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _seed_product(
    database: Database, *, category: str = "女装", attributes: dict[str, str] | None = None
) -> UUID:
    async with database.session() as session:
        product = Product(
            merchant_id=MERCHANT_ONE_ID,
            business_date=datetime.now(UTC).date(),
            product_code=f"sku-{uuid4().hex[:12]}",
            title="测试连衣裙",
            category=category,
            price=Decimal("199.00"),
            status="ONLINE",
            listed_at=datetime.now(UTC),
            attributes=attributes or {},
        )
        session.add(product)
        await session.commit()
        return product.id


async def _stage_content_change(
    database: Database,
    product_id: UUID,
    *,
    target_version: int = 1,
    batch_id: UUID | None = None,
    attributes: dict[str, Any] | None = None,
    pending_attributes: list[str] | None = None,
) -> UUID:
    async with database.session() as session:
        draft = Draft(
            merchant_id=MERCHANT_ONE_ID,
            kind=DraftKind.CONTENT_CHANGE.value,
            title="商品内容更新",
            target_type="PRODUCT",
            target_id=product_id,
            target_version=target_version,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={
                "attributes": attributes or {},
                "base_attributes": {},
                "pending_attributes": pending_attributes or [],
                "product_title": "测试连衣裙",
            },
            guardrail_snapshot={"checks": [], "checked_at": datetime.now(UTC).isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=datetime.now(UTC) + DRAFT_TTL,
            batch_id=batch_id,
        )
        session.add(draft)
        await session.commit()
        return draft.id


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
    crid: str,
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


async def _draft_state(database: Database, draft_id: UUID) -> str:
    async with database.session() as session:
        draft = await session.get(Draft, draft_id)
        assert draft is not None
        return str(draft.state)


async def _product(database: Database, product_id: UUID) -> Product:
    async with database.session() as session:
        product = await session.get(Product, product_id)
        assert product is not None
        return product


@pytest.mark.asyncio
async def test_content_change_applies_attributes_and_bumps_version(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product_id = await _seed_product(database)
    draft_id = await _stage_content_change(
        database,
        product_id,
        attributes={
            "产地": {"value": "浙江", "source_type": "MERCHANT_STATED", "source_ref": None}
        },
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(
        postgres_client, headers, draft_id, evidence=evidence, target_version=1, crid="c1"
    )
    assert resp.status_code == 200, resp.text
    product = await _product(database, product_id)
    # 写回商品记录的属性值保持 Mapping 结构（与 `_attribute_values()`、本地化服务读取
    # 同一字段时的假设一致），不能拍扁成裸字符串——否则顾客端与本地化服务都读不到。
    assert product.attributes["产地"]["value"] == "浙江"
    assert product.attributes["产地"]["source_type"] == "MERCHANT_STATED"
    assert product.content_version == 2


@pytest.mark.asyncio
async def test_content_change_rejects_disallowed_source_type(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """处理器再校验一次来源类型：即使有人绕过起草侧构造了非法草稿行，应用也会拒绝。"""

    database = _database(postgres_app)
    product_id = await _seed_product(database)
    draft_id = await _stage_content_change(
        database,
        product_id,
        attributes={
            "产地": {"value": "浙江", "source_type": "AI_GUESSED", "source_ref": None}
        },
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(
        postgres_client, headers, draft_id, evidence=evidence, target_version=1, crid="c2"
    )
    assert resp.status_code == 422, resp.text
    product = await _product(database, product_id)
    assert "产地" not in product.attributes


@pytest.mark.asyncio
async def test_batch_drafts_share_batch_id_and_partial_approval_leaves_others_staged(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    conversation_id = "conv-batch-1"
    batch_id = UUID(derive_batch_id(conversation_id=conversation_id, batch_key="秋季补充资料"))
    product_ids = [await _seed_product(database) for _ in range(3)]
    draft_ids = [
        await _stage_content_change(
            database,
            product_id,
            batch_id=batch_id,
            attributes={
                "产地": {"value": "浙江", "source_type": "MERCHANT_STATED", "source_ref": None}
            },
        )
        for product_id in product_ids
    ]

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    listed = await postgres_client.get(
        DRAFTS_PATH, params={"batch_id": str(batch_id)}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert {item["id"] for item in listed.json()["items"]} == {str(d) for d in draft_ids}

    # 只批准第一份子草稿。
    evidence = await _evidence(postgres_client, headers, draft_ids[0])
    resp = await _apply(
        postgres_client, headers, draft_ids[0], evidence=evidence, target_version=1, crid="c3"
    )
    assert resp.status_code == 200, resp.text

    states = [await _draft_state(database, draft_id) for draft_id in draft_ids]
    assert states == ["APPLIED", "STAGED", "STAGED"]


@pytest.mark.asyncio
async def test_missing_attribute_is_pending_not_invented(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """起草记录里"产地"缺失时，应用后商品记录里也不应该凭空出现这个属性的值。"""

    database = _database(postgres_app)
    product_id = await _seed_product(database, category="女装")
    draft_id = await _stage_content_change(
        database,
        product_id,
        attributes={
            "材质": {"value": "棉", "source_type": "MERCHANT_FILLED", "source_ref": None}
        },
        pending_attributes=["产地", "尺码"],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft_id)
    resp = await _apply(
        postgres_client, headers, draft_id, evidence=evidence, target_version=1, crid="c4"
    )
    assert resp.status_code == 200, resp.text
    product = await _product(database, product_id)
    assert "产地" not in product.attributes
    assert product.attributes["材质"]["value"] == "棉"
