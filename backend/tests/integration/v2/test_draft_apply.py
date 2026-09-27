"""草稿应用事务（模块 C Task 4，契约 §8.13.2、§8.7.9）——真实 PostgreSQL。

事务内的步骤顺序是固定的，且每一步失败都**不推进状态**：

```text
归属检查 → 幂等查询 → 取草稿并锁行 → 消费证据 → 基数复检 → 护栏复检 → 写库存 → 事件 → 账本
```

本文件按这个顺序逐条验证，另外证明三件容易写错的事：并发只有一个赢家、
失败时证据不被吃掉、跨店应用 403 且写审计。
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.models.analytics import Product
from app.models.drafts import ChangeLedger, Draft
from app.models.events import InventoryEvent
from app.models.operations import AuditLog, OperationEvidenceNonce
from app.models.promotion import GuardrailConfig
from app.repositories.v2.operation_evidence import OperationEvidenceRepository
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.draft_apply import DraftApplyService
from app.services.v2.drafts import AGENT_ACTOR, DRAFT_TTL
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_AUTH, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration

DRAFTS_PATH = "/api/v2/merchant/drafts"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _stage_restock(
    database: Database, merchant_id: UUID, product_id: UUID, *, delta: int, base: int
) -> UUID:
    """直接播种一条草稿：应用事务的用例不该依赖模型或工具链路是否可用。"""

    async with database.session() as session:
        draft = Draft(
            merchant_id=merchant_id,
            kind=DraftKind.RESTOCK.value,
            title=f"补货 +{delta}",
            target_type="PRODUCT",
            target_id=product_id,
            target_version=base,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={"delta": delta, "base_on_hand": base, "product_title": "测试商品"},
            guardrail_snapshot={"checks": [], "checked_at": datetime.now(UTC).isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=datetime.now(UTC) + DRAFT_TTL,
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
    evidence: str | None,
    crid: str = "apply-1",
    draft_version: int = 1,
    target_version: int | None = None,
    accepted_entry_ids: list[str] | None = None,
) -> Any:
    body: dict[str, Any] = {
        "client_request_id": crid,
        "draft_version": draft_version,
        "target_version": 12 if target_version is None else target_version,
    }
    if evidence is not None:
        body["approval_evidence"] = evidence
    if accepted_entry_ids is not None:
        body["accepted_entry_ids"] = accepted_entry_ids
    return await client.post(f"{DRAFTS_PATH}/{draft_id}/apply", json=body, headers=headers)


async def _draft_state(database: Database, draft_id: UUID) -> str:
    async with database.session() as session:
        return str((await session.get(Draft, draft_id)).state)  # type: ignore[union-attr]


async def _stock(database: Database, product_id: UUID) -> int:
    async with database.session() as session:
        return int((await session.get(Product, product_id)).stock_on_hand)  # type: ignore[union-attr]


async def _set_stock(database: Database, product_id: UUID, on_hand: int) -> None:
    async with database.session() as session:
        await session.execute(
            update(Product).where(Product.id == product_id).values(stock_on_hand=on_hand)
        )
        await session.commit()


async def _set_guardrail(database: Database, merchant_id: UUID, *, max_restock: int) -> None:
    async with database.session() as session:
        existing = await session.get(GuardrailConfig, merchant_id)
        if existing is None:
            session.add(
                GuardrailConfig(
                    merchant_id=merchant_id,
                    max_discount_rate=0,
                    max_price_change_rate=0,
                    max_restock_delta=max_restock,
                    updated_by="test",
                )
            )
        else:
            existing.max_restock_delta = max_restock
        await session.commit()


async def _consume_nonce(database: Database, token: str) -> None:
    """把证据里的 nonce 直接标为已消费，用来构造「已消费」这一类失败。"""

    from app.services.v2.approval_evidence import EVIDENCE_PURPOSE

    encoded = token.partition(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    async with database.session() as session:
        consumed = await OperationEvidenceRepository(session).consume(
            purpose=EVIDENCE_PURPOSE, nonce=payload["n"], now=datetime.now(UTC)
        )
        await session.commit()
    assert consumed is True


async def _count(database: Database, model: type[Any], **filters: Any) -> int:
    async with database.session() as session:
        statement = select(func.count()).select_from(model)
        for column, value in filters.items():
            statement = statement.where(getattr(model, column) == value)
        return int((await session.execute(statement)).scalar_one())


# --- 正常路径 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selected_diff_entry_can_use_detail_approval_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    detail = await _detail(postgres_client, headers, draft)
    entry_id = detail["diff"]["entries"][0]["entry_id"]

    response = await _apply(
        postgres_client,
        headers,
        draft,
        evidence=detail["approval_evidence"],
        accepted_entry_ids=[entry_id],
    )

    assert response.status_code == 200, response.text
    assert response.json()["ledger_entry"]["applied_entry_ids"] == [entry_id]
    assert await _stock(database, product) == 72


@pytest.mark.asyncio
async def test_unknown_selected_entry_cannot_apply_or_consume_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    detail = await _detail(postgres_client, headers, draft)
    evidence = detail["approval_evidence"]
    entry_id = detail["diff"]["entries"][0]["entry_id"]

    rejected = await _apply(
        postgres_client,
        headers,
        draft,
        evidence=evidence,
        crid="unknown-entry",
        accepted_entry_ids=["unrelated-entry"],
    )

    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "INVALID_REQUEST"
    assert await _draft_state(database, draft) == "STAGED"
    assert await _stock(database, product) == 12
    accepted = await _apply(
        postgres_client,
        headers,
        draft,
        evidence=evidence,
        crid="actual-entry",
        accepted_entry_ids=[entry_id],
    )
    assert accepted.status_code == 200, accepted.text
    assert await _stock(database, product) == 72


@pytest.mark.asyncio
async def test_apply_adds_stock_and_writes_the_ledger(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    resp = await _apply(postgres_client, headers, draft, evidence=evidence)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["draft"]["state"] == "APPLIED"
    assert body["ledger_entry"]["draft_id"] == str(draft)
    assert await _stock(database, product) == 72


@pytest.mark.asyncio
async def test_apply_writes_ledger_with_both_actors(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """账本同时记录起草者与批准者，以及应用时的护栏结果（D9③）。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    body = (await _apply(postgres_client, headers, draft, evidence=evidence)).json()

    entry = body["ledger_entry"]
    assert entry["drafted_by"]["actor_type"] == "AGENT"
    assert entry["approved_by"]["actor_type"] == "MERCHANT"
    assert entry["approved_at"]
    assert entry["guardrail_results"] and all(r["passed"] for r in entry["guardrail_results"])
    async with database.session() as session:
        ledger = (await session.execute(select(ChangeLedger))).scalars().one()
        assert ledger.draft_id == draft


@pytest.mark.asyncio
async def test_apply_appends_an_inventory_event(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    await _apply(postgres_client, headers, draft, evidence=evidence)

    async with database.session() as session:
        event = (await session.execute(select(InventoryEvent))).scalars().one()
    assert event.event_type == "MERCHANT_RESTOCK"
    assert event.subject_id == product
    assert event.payload["delta"] == 60


# --- 幂等与重放 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_retry_with_same_request_id_returns_first_result(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """§8.7.9：先查幂等再验证证据——网络重试不是重放。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    first = await _apply(postgres_client, headers, draft, evidence=evidence, crid="a1")
    retry = await _apply(postgres_client, headers, draft, evidence=evidence, crid="a1")

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert await _stock(database, product) == 72  # 只加一次
    for token in (None, "", "bad evidence", "x" * 2049):
        replay = await _apply(postgres_client, headers, draft, evidence=token, crid="a1")
        assert replay.status_code == 200, replay.text
        assert replay.json() == first.json()


@pytest.mark.asyncio
async def test_replay_shortcut_does_not_apply_to_other_input_or_other_key(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """同 ID 不同业务输入按 §8.7.3 优先返回幂等冲突，绝不再次写入。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    first = await _apply(postgres_client, headers, draft, evidence=evidence, crid="a1")
    assert first.status_code == 200

    other_key = await _apply(postgres_client, headers, draft, evidence="bad evidence", crid="a2")
    other_input = await _apply(
        postgres_client, headers, draft, evidence="bad evidence", crid="a1", target_version=99
    )

    assert other_key.status_code == 422
    assert other_key.json()["code"] == "CONFIRMATION_REQUIRED"
    assert other_input.status_code == 409
    assert other_input.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _stock(database, product) == 72  # 仍然只加了一次


@pytest.mark.asyncio
async def test_reusing_evidence_with_new_request_id_is_rejected(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """同一份证据换一个请求 ID 再用必须被拒，且不产生第二次业务写入（§8.7.9）。

    这条路径上有两道锁：nonce 已被消费，草稿也已经是终态。按固定步骤顺序，
    先撞上的是状态机，所以对外是 409——**重点是没有第二次写入**，
    而不是具体哪个码。证据本身也确实已消费，见末尾断言。
    """

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    assert (
        await _apply(postgres_client, headers, draft, evidence=evidence, crid="a1")
    ).status_code == 200
    replay = await _apply(postgres_client, headers, draft, evidence=evidence, crid="a2")

    assert replay.status_code == 409
    assert await _stock(database, product) == 72  # 没有第二次业务写入
    assert await _count(database, ChangeLedger) == 1
    async with database.session() as session:
        unconsumed = (
            (
                await session.execute(
                    select(OperationEvidenceNonce).where(
                        OperationEvidenceNonce.consumed_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert unconsumed == []


@pytest.mark.asyncio
async def test_concurrent_apply_has_one_winner(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """五个请求真正并发（各自独立的 ASGI 客户端与连接），只能有一个成功。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    async def attempt(index: int) -> int:
        async with AsyncClient(
            transport=ASGITransport(app=postgres_app), base_url="http://testserver"
        ) as client:
            resp = await _apply(client, headers, draft, evidence=evidence, crid=f"c{index}")
            return int(resp.status_code)

    statuses = await asyncio.gather(*(attempt(index) for index in range(5)))

    assert sum(1 for status in statuses if status == 200) == 1
    assert await _stock(database, product) == 72  # 只加一次
    assert await _count(database, ChangeLedger) == 1


# --- 失败路径：每一条都必须保持 STAGED --------------------------------------------


@pytest.mark.asyncio
async def test_stale_base_rejects_and_keeps_staged(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D9⑧：起草后库存被订单扣过，基数不匹配。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    await _set_stock(database, product, 10)  # 期间卖掉 2 件

    resp = await _apply(postgres_client, headers, draft, evidence=evidence)

    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "VERSION_CONFLICT"
    assert body["retryable"] is False
    assert body["details"] == [{"scope": "TARGET"}]
    assert await _draft_state(database, draft) == "STAGED"
    assert await _stock(database, product) == 10
    assert await _count(database, ChangeLedger) == 0


@pytest.mark.asyncio
async def test_failed_apply_does_not_consume_the_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """证据消费与业务写入同事务：复检失败回滚后，同一份证据仍然可用。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    await _set_stock(database, product, 10)
    assert (
        await _apply(postgres_client, headers, draft, evidence=evidence, crid="x1")
    ).status_code == 409

    await _set_stock(database, product, 12)  # 库存回到基数
    retry = await _apply(postgres_client, headers, draft, evidence=evidence, crid="x2")

    assert retry.status_code == 200, retry.text
    async with database.session() as session:
        consumed = (
            (
                await session.execute(
                    select(OperationEvidenceNonce).where(
                        OperationEvidenceNonce.consumed_at.is_not(None)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(consumed) == 1


@pytest.mark.asyncio
async def test_guardrail_rechecked_with_current_config(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D9②：预检通过，但应用前护栏收紧了。"""

    database = _database(postgres_app)
    await _set_guardrail(database, MERCHANT_ONE_ID, max_restock=200)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=150, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    await _set_guardrail(database, MERCHANT_ONE_ID, max_restock=100)

    resp = await _apply(postgres_client, headers, draft, evidence=evidence)

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "GUARDRAIL_REJECTED"
    assert body["details"][0]["code"] == "RESTOCK_DELTA_EXCEEDS_LIMIT"
    assert body["details"][0]["passed"] is False
    assert await _draft_state(database, draft) == "STAGED"
    assert await _stock(database, product) == 12


@pytest.mark.asyncio
async def test_expired_draft_is_rejected_without_the_cron_job(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """过期判定在业务路径上自检，不依赖清理任务是否已跑。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    async with database.session() as session:
        await session.execute(
            update(Draft)
            .where(Draft.id == draft)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    resp = await _apply(postgres_client, headers, draft, evidence=evidence)

    assert resp.status_code == 409
    assert resp.json()["code"] == "DRAFT_EXPIRED"
    assert await _draft_state(database, draft) == "EXPIRED"
    assert await _stock(database, product) == 12


@pytest.mark.asyncio
async def test_draft_version_mismatch_is_a_version_conflict(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """契约 §8.13.2 不变量 2：请求里的草案版本与服务端不符 → 409（scope=DRAFT）。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)

    resp = await _apply(postgres_client, headers, draft, evidence=evidence, draft_version=2)

    assert resp.status_code == 409
    assert resp.json()["details"] == [{"scope": "DRAFT"}]
    assert await _draft_state(database, draft) == "STAGED"


@pytest.mark.asyncio
async def test_evidence_is_invalid_after_the_draft_changes(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D9⑦：草案内容变更后旧批准失效——证据绑定了草案版本。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    async with database.session() as session:
        await session.execute(
            update(Draft)
            .where(Draft.id == draft)
            .values(draft_version=2, payload={"delta": 90, "base_on_hand": 12})
        )
        await session.commit()

    resp = await _apply(postgres_client, headers, draft, evidence=evidence, draft_version=2)

    assert resp.status_code == 422
    assert resp.json()["code"] == "CONFIRMATION_REQUIRED"
    assert await _draft_state(database, draft) == "STAGED"


@pytest.mark.asyncio
async def test_evidence_is_bound_to_the_issuing_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """同一商家的另一个会话也用不了：主体绑定到会话记录，不只是商家。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    first = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    second = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, first, draft)

    resp = await _apply(postgres_client, second, draft, evidence=evidence)

    assert resp.status_code == 422
    assert resp.json()["code"] == "CONFIRMATION_REQUIRED"
    assert await _draft_state(database, draft) == "STAGED"


@pytest.mark.asyncio
async def test_all_evidence_failures_are_indistinguishable(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.7.9：五类证据失败对外同一中性结构——逐字段比较，不只比状态码。

    「已消费」这一类直接把 nonce 标记为已消费来构造：在自然路径上，一份被消费过的
    证据同时意味着草稿已是终态，那就会先撞状态机。这里要验证的是**响应形状不因
    失败原因而不同**，所以必须把草稿留在 `STAGED`，只让证据这一个变量变化。
    """

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    other = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=30, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    valid = await _evidence(postgres_client, headers, draft)
    for_other_draft = await _evidence(postgres_client, headers, other)
    consumed = await _evidence(postgres_client, headers, draft)
    await _consume_nonce(database, consumed)
    payload, _, signature = valid.partition(".")
    tampered = f"{payload}A.{signature}"

    responses = [
        await _apply(postgres_client, headers, draft, evidence=None, crid="x1"),
        await _apply(postgres_client, headers, draft, evidence=tampered, crid="x2"),
        await _apply(postgres_client, headers, draft, evidence="not.atoken", crid="x3"),
        await _apply(postgres_client, headers, draft, evidence=for_other_draft, crid="x4"),
        await _apply(postgres_client, headers, draft, evidence=consumed, crid="x5"),
    ]

    from app.services.v2.approval_evidence import ApprovalEvidenceService

    verify = ApprovalEvidenceService.verify
    with monkeypatch.context() as patch:
        # 只推进证据校验时钟；草稿保持 STAGED，确认命中的是证据过期路径。
        patch.setattr(
            ApprovalEvidenceService,
            "verify",
            lambda self, token, binding, *, now: verify(
                self, token, binding, now=now + timedelta(minutes=11)
            ),
        )
        responses.append(await _apply(postgres_client, headers, draft, evidence=valid, crid="x6"))

    normalized = [
        {key: value for key, value in resp.json().items() if key != "request_id"}
        for resp in responses
    ]
    assert {resp.status_code for resp in responses} == {422}
    assert all(item == normalized[0] for item in normalized), normalized
    assert normalized[0]["code"] == "CONFIRMATION_REQUIRED"
    assert normalized[0]["details"] == []
    assert await _draft_state(database, draft) == "STAGED"
    assert await _stock(database, product) == 12


@pytest.mark.asyncio
async def test_terminal_draft_answers_the_same_way_to_every_token(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """终态草稿上，响应只由状态决定，不因证据真假而不同——没有令牌有效性预言机。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    used = await _evidence(postgres_client, headers, draft)
    fresh = await _evidence(postgres_client, headers, draft)
    assert (
        await _apply(postgres_client, headers, draft, evidence=used, crid="t0")
    ).status_code == 200

    responses = [
        await _apply(postgres_client, headers, draft, evidence=used, crid="t1"),
        await _apply(postgres_client, headers, draft, evidence=fresh, crid="t2"),
        await _apply(postgres_client, headers, draft, evidence="not.atoken", crid="t3"),
    ]

    normalized = [
        {key: value for key, value in resp.json().items() if key != "request_id"}
        for resp in responses
    ]
    assert {resp.status_code for resp in responses} == {409}
    assert all(item == normalized[0] for item in normalized), normalized
    assert normalized[0]["code"] == "ILLEGAL_STATE_TRANSITION"
    assert await _stock(database, product) == 72


@pytest.mark.asyncio
async def test_terminal_states_cannot_be_applied_again(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    assert (
        await _apply(postgres_client, headers, draft, evidence=evidence, crid="one")
    ).status_code == 200
    second_evidence_attempt = await postgres_client.get(f"{DRAFTS_PATH}/{draft}", headers=headers)

    resp = await _apply(
        postgres_client, headers, draft, evidence=evidence, crid="two", target_version=72
    )

    assert second_evidence_attempt.json()["approval_evidence"] is None
    assert resp.status_code == 409
    assert resp.json()["code"] == "ILLEGAL_STATE_TRANSITION"
    assert resp.json()["details"] == [{"state": "APPLIED"}]


# --- 跨店与鉴权 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_shop_apply_forbidden_and_audited(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """第 0 步在第 1 步之前：不属于你的草稿，连有没有幂等记录都不该暴露。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_TWO_ID, on_hand=12)
    theirs = await _stage_restock(database, MERCHANT_TWO_ID, product, delta=60, base=12)
    theirs_headers = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    evidence = await _evidence(postgres_client, theirs_headers, theirs)
    mine = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await _apply(postgres_client, mine, theirs, evidence=evidence)

    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"
    assert resp.json()["details"] == []
    assert await _stock(database, product) == 12
    assert (
        await _count(
            database,
            AuditLog,
            event_type="RESOURCE_SCOPE_VIOLATION",
            merchant_id=MERCHANT_ONE_ID,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_missing_draft_is_indistinguishable_from_someone_elses(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """R5：目标不存在与不属于当前主体使用相同公开错误结构。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_TWO_ID, on_hand=12)
    theirs = await _stage_restock(database, MERCHANT_TWO_ID, product, delta=60, base=12)
    mine = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    missing = await postgres_client.get(f"{DRAFTS_PATH}/{uuid4()}", headers=mine)
    forbidden = await postgres_client.get(f"{DRAFTS_PATH}/{theirs}", headers=mine)

    assert missing.status_code == forbidden.status_code == 403
    assert {k: v for k, v in missing.json().items() if k != "request_id"} == {
        k: v for k, v in forbidden.json().items() if k != "request_id"
    }


@pytest.mark.asyncio
async def test_draft_detail_is_not_cacheable(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get(f"{DRAFTS_PATH}/{draft}", headers=headers)

    assert "no-store" in resp.headers["cache-control"]


@pytest.mark.asyncio
async def test_repeated_reads_issue_distinct_single_use_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _evidence(postgres_client, headers, draft)
    second = await _evidence(postgres_client, headers, draft)

    assert first != second
    assert (
        await _apply(postgres_client, headers, draft, evidence=first, crid="r1")
    ).status_code == 200
    # 第二份 nonce 还没被消费，但草稿已是终态——先撞状态机，不会再生效一次。
    assert (
        await _apply(postgres_client, headers, draft, evidence=second, crid="r2", target_version=72)
    ).status_code == 409
    assert await _stock(database, product) == 72


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "", "bad evidence", "x" * 2049, "not.atoken"])
async def test_identity_and_scope_precede_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient, token: str | None
) -> None:
    from tests.integration.v2.test_shop_chat import _guest

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_TWO_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_TWO_ID, product, delta=60, base=12)
    customer = await _guest(postgres_client)
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    for headers, expected in (({}, 401), (customer, 403), (merchant, 403)):
        for target in (draft, uuid4()):
            response = await _apply(postgres_client, headers, target, evidence=token)
            assert response.status_code == expected, response.text
    assert await _count(database, AuditLog, event_type="RESOURCE_SCOPE_VIOLATION") == 2
    assert await _stock(database, product) == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["apply", "discard"])
async def test_apply_discard_race_rechecks_locked_state(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    winner: str,
) -> None:
    from app.api.routes.v2 import merchant_drafts

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, draft)
    read, resume = asyncio.Event(), asyncio.Event()
    original = merchant_drafts._require_owned_draft

    async def paused(request: Any, *args: Any, **kwargs: Any) -> Draft:
        row = await original(request, *args, **kwargs)
        if request.method == ("DELETE" if winner == "apply" else "POST"):
            read.set()
            await asyncio.wait_for(resume.wait(), 10)
        return row

    monkeypatch.setattr(merchant_drafts, "_require_owned_draft", paused)
    async with AsyncClient(
        transport=ASGITransport(app=postgres_app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:

        async def apply() -> Any:
            return await _apply(client, headers, draft, evidence=evidence)

        async def discard() -> Any:
            return await client.delete(f"{DRAFTS_PATH}/{draft}", headers=headers)

        losing = asyncio.create_task(discard() if winner == "apply" else apply())
        try:
            await asyncio.wait_for(read.wait(), 5)
            winning = await (apply() if winner == "apply" else discard())
        finally:
            resume.set()
        lost = await asyncio.wait_for(losing, 10)
    assert winning.status_code == (200 if winner == "apply" else 204), winning.text
    assert lost.status_code == 409, lost.text
    assert lost.json()["code"] == "ILLEGAL_STATE_TRANSITION"
    assert await _draft_state(database, draft) == ("APPLIED" if winner == "apply" else "DISCARDED")
    assert await _stock(database, product) == (72 if winner == "apply" else 12)
    assert await _count(database, ChangeLedger) == (1 if winner == "apply" else 0)
    assert await _count(database, InventoryEvent) == (1 if winner == "apply" else 0)


@pytest.mark.asyncio
async def test_discard_must_not_overwrite_applied(postgres_app, postgres_client, monkeypatch):
    from app.api.routes.v2 import merchant_drafts

    db = postgres_app.state.database
    pid = await seed_product(db, MERCHANT_ONE_ID, on_hand=12)
    did = await _stage_restock(db, MERCHANT_ONE_ID, pid, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, did)
    read = asyncio.Event()
    resume = asyncio.Event()
    original = merchant_drafts._require_owned_draft

    async def paused(request, *args, **kwargs):
        result = await original(request, *args, **kwargs)
        if request.method == "DELETE":
            read.set()
            await resume.wait()
        return result

    monkeypatch.setattr(merchant_drafts, "_require_owned_draft", paused)
    from httpx import ASGITransport, AsyncClient

    transport_client = AsyncClient(
        transport=ASGITransport(app=postgres_app, raise_app_exceptions=False),
        base_url="http://testserver",
    )
    deletion = asyncio.create_task(
        transport_client.delete(f"/api/v2/merchant/drafts/{did}", headers=headers)
    )
    await asyncio.wait_for(read.wait(), 5)
    try:
        applied = await _apply(postgres_client, headers, did, evidence=evidence)
    finally:
        resume.set()
    deleted = await deletion
    state = await _draft_state(db, did)
    assert applied.status_code == 200
    await transport_client.aclose()
    assert state == "APPLIED"
    assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_lock_refreshes_stale_identity_map_entry(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """`_lock()` 必须看见另一事务已提交的最新状态，即使调用方在加锁前已经持有旧对象。

    路由层的归属检查（`_require_owned_draft`）会用同一个 `Session` 先读一次草稿，
    把它放进 SQLAlchemy 的身份映射；`DraftApplyService._lock()` 随后在同一个 `Session`
    上执行 `FOR UPDATE`。若不加 `populate_existing=True`，`FOR UPDATE` 解锁后返回的
    仍是身份映射里那份旧属性，而不是数据库里的最新值——这里直接在同一个 `AsyncSession`
    内复现「先持有旧对象，再并发丢弃，再加锁读取」的顺序，不依赖对象是否被垃圾回收，
    因此不会像 `test_apply_discard_race_rechecks_locked_state` 那样偶然因为没人持有
    引用而侥幸通过。
    """

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    draft_id = await _stage_restock(database, MERCHANT_ONE_ID, product, delta=60, base=12)

    async with database.session() as session:
        # 模拟路由层的归属检查：用这个 Session 先读一次，对象进入身份映射。
        stale = (
            await session.execute(select(Draft).where(Draft.id == draft_id))
        ).scalar_one()
        assert stale.state == DraftState.STAGED.value

        # 另一个独立事务并发丢弃这份草稿并提交，产生身份映射之外的最新状态。
        async with database.session() as other_session:
            other_draft = await other_session.get(Draft, draft_id)
            assert other_draft is not None
            other_draft.state = DraftState.DISCARDED.value
            await other_session.commit()

        ctx = SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.MERCHANT,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key=None,
            shop_slug=None,
        )
        service = DraftApplyService(
            session, database=database, evidence=cast(Any, None), ctx=ctx
        )
        locked = await service._lock(draft_id)

    assert locked.state == DraftState.DISCARDED.value
    assert locked is stale  # 同一身份映射对象被原地刷新，而不是返回了另一份


@pytest.mark.asyncio
async def test_auth_before_missing_evidence(postgres_client):
    response = await postgres_client.post(
        f"/api/v2/merchant/drafts/{uuid4()}/apply",
        json={"client_request_id": "audit", "draft_version": 1, "target_version": 12},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_customer_missing_evidence_must_be_role_403(postgres_client):
    from tests.integration.v2.test_shop_chat import _guest

    headers = await _guest(postgres_client)
    response = await postgres_client.post(
        f"/api/v2/merchant/drafts/{uuid4()}/apply",
        headers=headers,
        json={"client_request_id": "audit-role", "draft_version": 1, "target_version": 12},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", [None, "invalid token !"])
async def test_foreign_draft_ownership_precedes_evidence(postgres_app, postgres_client, evidence):
    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_TWO_ID, on_hand=12)
    did = await _stage_restock(database, MERCHANT_TWO_ID, pid, delta=60, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await _apply(postgres_client, headers, did, evidence=evidence)
    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"
    async with database.session() as session:
        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.request_id == response.json()["request_id"],
                AuditLog.event_type == "RESOURCE_SCOPE_VIOLATION",
            )
        )
    assert audit is not None
