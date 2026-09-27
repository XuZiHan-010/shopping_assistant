"""N1 D：会话与来源状态表的 PostgreSQL 约束与触发器验收。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import DBAPIError

from app.models.provenance import ConversationProvenance
from app.models.session import AgentSession
from tests.integration._db_asserts import (
    CHECK_VIOLATION,
    RAISE_EXCEPTION,
    UNIQUE_VIOLATION,
    assert_sqlstate,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _customer_session(merchant_id, **overrides):
    values = {
        "id": uuid4(),
        "token_fingerprint": uuid4().hex + uuid4().hex,
        "role": "CUSTOMER",
        "merchant_id": merchant_id,
        "buyer_key": None,
        "shop_slug": "borough-100",
        "issuer_fingerprint": None,
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return values


def _merchant_session(merchant_id, **overrides):
    values = {
        "id": uuid4(),
        "token_fingerprint": uuid4().hex + uuid4().hex,
        "role": "MERCHANT",
        "merchant_id": merchant_id,
        "buyer_key": None,
        "shop_slug": None,
        "issuer_fingerprint": (uuid4().hex + uuid4().hex),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_merchant_session_rejects_buyer_key_and_shop_slug(db_session, merchant_one_id):
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AgentSession).values(_merchant_session(merchant_one_id, buyer_key="bk-1"))
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_agent_sessions_merchant_no_buyer_key")

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AgentSession).values(_merchant_session(merchant_one_id, shop_slug="s"))
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_agent_sessions_merchant_no_shop_slug")


@pytest.mark.asyncio
async def test_customer_session_requires_shop_slug_and_rejects_issuer(db_session, merchant_one_id):
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AgentSession).values(_customer_session(merchant_one_id, shop_slug=None))
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_agent_sessions_customer_requires_shop_slug")

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AgentSession).values(
                    _customer_session(merchant_one_id, issuer_fingerprint="f" * 64)
                )
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_agent_sessions_customer_no_issuer")


@pytest.mark.asyncio
async def test_merchant_session_requires_issuer_fingerprint(db_session, merchant_one_id):
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AgentSession).values(
                    _merchant_session(merchant_one_id, issuer_fingerprint=None)
                )
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_agent_sessions_merchant_requires_issuer")


@pytest.mark.asyncio
async def test_identity_columns_are_immutable_after_insert(
    db_session, merchant_one_id, merchant_two_id
):
    session_id = (
        await db_session.execute(
            insert(AgentSession)
            .values(_customer_session(merchant_one_id))
            .returning(AgentSession.id)
        )
    ).scalar_one()

    for statement in (
        update(AgentSession).where(AgentSession.id == session_id).values(role="MERCHANT"),
        update(AgentSession)
        .where(AgentSession.id == session_id)
        .values(merchant_id=merchant_two_id),
        update(AgentSession).where(AgentSession.id == session_id).values(shop_slug="other-shop"),
    ):
        with pytest.raises(DBAPIError) as error:
            async with db_session.begin_nested():
                await db_session.execute(statement)
        assert_sqlstate(error, RAISE_EXCEPTION)

    # 首次绑定 buyer_key（NULL → 值）必须被允许。
    await db_session.execute(
        update(AgentSession).where(AgentSession.id == session_id).values(buyer_key="bk-1")
    )
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                update(AgentSession).where(AgentSession.id == session_id).values(buyer_key="bk-2")
            )
    assert_sqlstate(error, RAISE_EXCEPTION)


@pytest.mark.asyncio
async def test_conversation_provenance_rejects_unknown_principal_kind(db_session, merchant_one_id):
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(ConversationProvenance).values(
                    id=uuid4(),
                    principal_kind="ADMIN",
                    principal_id="p-1",
                    merchant_id=merchant_one_id,
                    conversation_id="c-1",
                    object_type="PRODUCT",
                    object_id="p-9",
                    version=1,
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                )
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_conversation_provenance_principal_kind")


@pytest.mark.asyncio
async def test_conversation_provenance_scope_is_unique(db_session, merchant_one_id):
    values = {
        "id": uuid4(),
        "principal_kind": "GUEST_SESSION",
        "principal_id": "p-1",
        "merchant_id": merchant_one_id,
        "conversation_id": "c-1",
        "object_type": "PRODUCT",
        "object_id": "p-9",
        "version": 1,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
    }
    await db_session.execute(insert(ConversationProvenance).values(values))
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(ConversationProvenance).values({**values, "id": uuid4()})
            )
    assert_sqlstate(error, UNIQUE_VIOLATION, "uq_conversation_provenance_scope")
