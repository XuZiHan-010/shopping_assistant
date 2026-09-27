"""商家回答反馈（PRD M13，契约 §8.14.4）：`POST /api/v2/merchant/answers/{answer_id}/feedback`。

真实 PostgreSQL；不调用 v2 Chat 路由（尚未落地），直接在测试库里播种一条 v1 `Answer`，
因为反馈路由只依赖 `answer_id` 所属的 `merchant_id`，与该回答是经 v1 还是 v2 Chat 产生无关。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.models.answer import Answer
from app.models.conversation import Conversation
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_AUTH, MERCHANT_TWO_ID

FEEDBACK_PATH = "/api/v2/merchant/answers/{answer_id}/feedback"


async def _seed_answer(database: Database, merchant_id: UUID) -> UUID:
    async with database.session() as session:
        conversation = Conversation(merchant_id=merchant_id)
        session.add(conversation)
        await session.flush()
        answer = Answer(
            merchant_id=merchant_id,
            conversation_id=conversation.id,
            client_request_id=f"seed-{uuid4()}",
            request_digest="seed-digest",
            processing_status="SUCCEEDED",
            response_payload={"answer": "seed"},
            response_locale="zh-CN",
        )
        session.add(answer)
        await session.commit()
        return answer.id


async def _merchant_session(client: AsyncClient, auth: dict[str, str]) -> dict[str, str]:
    resp = await client.post("/api/v2/merchant/sessions", json={}, headers=auth)
    assert resp.status_code == 201, resp.text
    return {"X-Session-Id": resp.json()["session_id"]}


async def _feedback(
    client: AsyncClient, headers: dict[str, str], answer_id: Any, body: dict[str, Any]
) -> Any:
    return await client.post(FEEDBACK_PATH.format(answer_id=answer_id), json=body, headers=headers)


@pytest.mark.asyncio
async def test_adoption_and_reaction_do_not_overwrite_each_other(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    answer_id = await _seed_answer(database, MERCHANT_ONE_ID)
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)

    first = await _feedback(
        postgres_client,
        headers,
        answer_id,
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-adopt-1"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["adopted"] is True
    assert first.json()["reaction"] is None

    second = await _feedback(
        postgres_client,
        headers,
        answer_id,
        {
            "kind": "REACTION",
            "reaction": "DISLIKE",
            "reason": "数字不对",
            "client_request_id": "fb-react-1",
        },
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["adopted"] is True
    assert body["reaction"] == "DISLIKE"
    assert body["reason"] == "数字不对"


@pytest.mark.asyncio
async def test_reaction_does_not_reset_prior_adoption(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    answer_id = await _seed_answer(database, MERCHANT_ONE_ID)
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)

    await _feedback(
        postgres_client,
        headers,
        answer_id,
        {"kind": "REACTION", "reaction": "LIKE", "client_request_id": "fb-like-1"},
    )
    resp = await _feedback(
        postgres_client,
        headers,
        answer_id,
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-adopt-2"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["adopted"] is True
    assert body["reaction"] == "LIKE"


@pytest.mark.asyncio
async def test_foreign_answer_feedback_is_forbidden(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    answer_id = await _seed_answer(database, MERCHANT_TWO_ID)
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)

    resp = await _feedback(
        postgres_client,
        headers,
        answer_id,
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-cross-1"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_missing_answer_feedback_is_indistinguishable_from_foreign(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    foreign_answer_id = await _seed_answer(database, MERCHANT_TWO_ID)
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)

    missing = await _feedback(
        postgres_client,
        headers,
        uuid4(),
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-missing-1"},
    )
    foreign = await _feedback(
        postgres_client,
        headers,
        foreign_answer_id,
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-missing-2"},
    )
    assert missing.status_code == foreign.status_code == 403
    missing_body = {k: v for k, v in missing.json().items() if k != "request_id"}
    foreign_body = {k: v for k, v in foreign.json().items() if k != "request_id"}
    assert missing_body == foreign_body


@pytest.mark.asyncio
async def test_customer_session_cannot_submit_feedback(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    guest = await postgres_client.post(
        "/api/v2/shop/sessions", json={"shop_slug": "borough-api-100"}
    )
    assert guest.status_code == 201, guest.text
    headers = {"X-Session-Id": guest.json()["session_id"]}

    resp = await _feedback(
        postgres_client,
        headers,
        uuid4(),
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-role-1"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"


@pytest.mark.asyncio
async def test_same_client_request_id_replays_same_response(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    answer_id = await _seed_answer(database, MERCHANT_ONE_ID)
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)
    body = {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-idem-1"}

    first = await _feedback(postgres_client, headers, answer_id, body)
    second = await _feedback(postgres_client, headers, answer_id, body)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


@pytest.mark.asyncio
async def test_same_client_request_id_with_different_body_is_conflict(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    answer_id = await _seed_answer(database, MERCHANT_ONE_ID)
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)

    first = await _feedback(
        postgres_client,
        headers,
        answer_id,
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-reuse-1"},
    )
    assert first.status_code == 200

    second = await _feedback(
        postgres_client,
        headers,
        answer_id,
        {"kind": "ADOPTION", "adopted": False, "client_request_id": "fb-reuse-1"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_two_merchants_reusing_same_client_request_id_do_not_collide(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """v2 幂等域含主体摘要，不同商家复用同一 client_request_id 不得互相冲突（§8.7.3）。"""

    database: Database = postgres_app.state.database
    answer_one = await _seed_answer(database, MERCHANT_ONE_ID)
    answer_two = await _seed_answer(database, MERCHANT_TWO_ID)
    headers_one = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)
    headers_two = await _merchant_session(postgres_client, MERCHANT_TWO_AUTH)

    resp_one = await _feedback(
        postgres_client,
        headers_one,
        answer_one,
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-shared-id"},
    )
    resp_two = await _feedback(
        postgres_client,
        headers_two,
        answer_two,
        {"kind": "ADOPTION", "adopted": False, "client_request_id": "fb-shared-id"},
    )

    assert resp_one.status_code == 200
    assert resp_two.status_code == 200
    assert resp_one.json()["adopted"] is True
    assert resp_two.json()["adopted"] is False


@pytest.mark.asyncio
async def test_malformed_answer_id_is_forbidden_not_validation_error(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await _merchant_session(postgres_client, MERCHANT_ONE_AUTH)

    resp = await _feedback(
        postgres_client,
        headers,
        "not-a-uuid",
        {"kind": "ADOPTION", "adopted": True, "client_request_id": "fb-malformed-1"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"
