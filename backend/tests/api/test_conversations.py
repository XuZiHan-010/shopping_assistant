"""会话列表、详情与删除的 HTTP 契约测试。

跑在真实 PostgreSQL 上：§8.0 要求每条路由都有「未认证」和「跨商家越权」用例，
而越权必须同时写 audit_logs——用假 Repository 证明不了这一点。
"""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models.operations import AuditLog
from tests.conftest import (
    MERCHANT_ONE_AUTH,
    MERCHANT_ONE_ID,
    MERCHANT_TWO_AUTH,
    MERCHANT_TWO_ID,
)

pytestmark = pytest.mark.asyncio


async def start_conversation(
    client: AsyncClient,
    auth: dict[str, str],
    message: str = "昨天总 GMV 是多少？",
    key: str = "conversation-seed",
) -> str:
    response = await client.post(
        "/api/chat",
        headers={**auth, "Accept": "application/json"},
        json={"message": message, "client_request_id": key},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["session_id"])


async def audit_rows(app: FastAPI) -> list[AuditLog]:
    async with app.state.database.session() as session:
        return list(await session.scalars(select(AuditLog)))


async def test_conversation_routes_require_authentication(
    postgres_client: AsyncClient,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH)

    responses = [
        await postgres_client.get("/api/conversations"),
        await postgres_client.get(f"/api/conversations/{conversation_id}"),
        await postgres_client.delete(f"/api/conversations/{conversation_id}"),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["code"] == "AUTH_REQUIRED"


async def test_list_returns_only_conversations_of_the_authenticated_merchant(
    postgres_client: AsyncClient,
) -> None:
    mine = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="mine-1")
    await start_conversation(postgres_client, MERCHANT_TWO_AUTH, key="theirs-1")

    response = await postgres_client.get("/api/conversations", headers=MERCHANT_ONE_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [mine]
    assert body["limit"] == 20
    assert body["offset"] == 0


async def test_list_rejects_out_of_range_pagination(
    postgres_client: AsyncClient,
) -> None:
    response = await postgres_client.get(
        "/api/conversations",
        headers=MERCHANT_ONE_AUTH,
        params={"limit": 500},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_detail_returns_messages_in_creation_order(
    postgres_client: AsyncClient,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="detail-1")

    response = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == conversation_id
    assert [message["role"] for message in body["messages"]] == ["USER", "ASSISTANT"]
    assert body["messages"][0]["content"] == "昨天总 GMV 是多少？"


async def test_cross_merchant_detail_returns_audited_scope_error(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="scope-1")

    response = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_TWO_AUTH,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"

    audits = await audit_rows(postgres_app)
    assert len(audits) == 1
    assert audits[0].event_type == "MERCHANT_SCOPE_VIOLATION"
    assert audits[0].merchant_id == MERCHANT_TWO_ID
    assert audits[0].resource_id == conversation_id


async def test_unknown_conversation_is_not_reported_as_scope_violation(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    response = await postgres_client.get(
        f"/api/conversations/{uuid4()}",
        headers=MERCHANT_ONE_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    # 不存在的资源不写审计，否则日志会被随机 UUID 探测刷爆。
    assert await audit_rows(postgres_app) == []


async def test_delete_removes_the_conversation_and_returns_204(
    postgres_client: AsyncClient,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="delete-1")

    deleted = await postgres_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )
    after = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )
    listing = await postgres_client.get("/api/conversations", headers=MERCHANT_ONE_AUTH)

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert after.status_code == 404
    assert listing.json()["items"] == []


async def test_cross_merchant_delete_is_forbidden_and_audited(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="scope-2")

    response = await postgres_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_TWO_AUTH,
    )
    still_there = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"
    assert still_there.status_code == 200

    audits = await audit_rows(postgres_app)
    assert [audit.merchant_id for audit in audits] == [MERCHANT_TWO_ID]


async def test_deleting_an_unknown_conversation_returns_404(
    postgres_client: AsyncClient,
) -> None:
    response = await postgres_client.delete(
        f"/api/conversations/{uuid4()}",
        headers=MERCHANT_ONE_AUTH,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_follow_up_turn_is_visible_in_the_conversation_detail(
    postgres_client: AsyncClient,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="follow-1")

    follow_up = await postgres_client.post(
        "/api/chat",
        headers={**MERCHANT_ONE_AUTH, "Accept": "application/json"},
        json={
            "message": "最近7天退货量趋势",
            "session_id": conversation_id,
            "client_request_id": "follow-2",
        },
    )
    detail = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )

    assert follow_up.status_code == 200
    assert follow_up.json()["session_id"] == conversation_id
    assert [message["role"] for message in detail.json()["messages"]] == [
        "USER",
        "ASSISTANT",
        "USER",
        "ASSISTANT",
    ]


async def test_another_merchant_cannot_post_into_a_foreign_session(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    conversation_id = await start_conversation(postgres_client, MERCHANT_ONE_AUTH, key="scope-3")

    response = await postgres_client.post(
        "/api/chat",
        headers={**MERCHANT_TWO_AUTH, "Accept": "application/json"},
        json={
            "message": "昨天总 GMV 是多少？",
            "session_id": conversation_id,
            "client_request_id": "intruder-1",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"
    assert [audit.merchant_id for audit in await audit_rows(postgres_app)] == [MERCHANT_TWO_ID]


async def test_request_body_merchant_id_cannot_widen_the_data_scope(
    postgres_client: AsyncClient,
) -> None:
    """身份只来自 Bearer Token；请求体里的 merchant_id 必须被忽略。"""

    response = await postgres_client.post(
        "/api/chat",
        headers={**MERCHANT_TWO_AUTH, "Accept": "application/json"},
        json={
            "message": "昨天总 GMV 是多少？",
            "client_request_id": "spoof-1",
            "merchant_id": str(MERCHANT_ONE_ID),
        },
    )
    listing_one = await postgres_client.get("/api/conversations", headers=MERCHANT_ONE_AUTH)
    listing_two = await postgres_client.get("/api/conversations", headers=MERCHANT_TWO_AUTH)

    assert response.status_code == 200
    assert listing_one.json()["items"] == []
    assert [item["id"] for item in listing_two.json()["items"]] == [
        str(response.json()["session_id"])
    ]
