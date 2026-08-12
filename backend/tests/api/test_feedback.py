"""POST /api/answers/{answer_id}/feedback 的 HTTP 契约测试。

跑在真实 PostgreSQL 上：§8.0 要求每条路由都有「未认证」和「跨商家越权」用例，
越权还必须写 audit_logs——这些只有走真实 HTTP + 真实数据库才能证伪。
"""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models.operations import AuditLog
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_TWO_AUTH, MERCHANT_TWO_ID

pytestmark = pytest.mark.asyncio


async def ask(
    client: AsyncClient,
    auth: dict[str, str],
    key: str,
    message: str = "昨天总 GMV 是多少？",
) -> str:
    response = await client.post(
        "/api/chat",
        headers={**auth, "Accept": "application/json"},
        json={"message": message, "client_request_id": key},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


async def audit_rows(app: FastAPI) -> list[AuditLog]:
    async with app.state.database.session() as session:
        return list(await session.scalars(select(AuditLog)))


async def test_feedback_requires_authentication(postgres_client: AsyncClient) -> None:
    answer_id = await ask(postgres_client, MERCHANT_ONE_AUTH, "feedback-auth-1")

    response = await postgres_client.post(
        f"/api/answers/{answer_id}/feedback",
        json={"is_adopted": True, "reaction": "LIKE"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


async def test_feedback_upserts_like_and_then_replaces_it_with_dislike(
    postgres_client: AsyncClient,
) -> None:
    answer_id = await ask(postgres_client, MERCHANT_ONE_AUTH, "feedback-idempotent-1")

    liked = await postgres_client.post(
        f"/api/answers/{answer_id}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True, "reaction": "LIKE"},
    )
    disliked = await postgres_client.post(
        f"/api/answers/{answer_id}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True, "reaction": "DISLIKE"},
    )

    assert liked.status_code == 200
    assert liked.json() == {"answer_id": answer_id, "is_adopted": True, "reaction": "LIKE"}
    assert disliked.status_code == 200
    assert disliked.json() == {"answer_id": answer_id, "is_adopted": True, "reaction": "DISLIKE"}


async def test_feedback_for_unknown_answer_returns_404(postgres_client: AsyncClient) -> None:
    response = await postgres_client.post(
        f"/api/answers/{uuid4()}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True, "reaction": "LIKE"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_cross_merchant_feedback_is_forbidden_and_audited(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    answer_id = await ask(postgres_client, MERCHANT_ONE_AUTH, "feedback-scope-1")

    response = await postgres_client.post(
        f"/api/answers/{answer_id}/feedback",
        headers=MERCHANT_TWO_AUTH,
        json={"is_adopted": True, "reaction": "LIKE"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "MERCHANT_SCOPE_VIOLATION"

    audits = await audit_rows(postgres_app)
    assert len(audits) == 1
    assert audits[0].event_type == "MERCHANT_SCOPE_VIOLATION"
    assert audits[0].merchant_id == MERCHANT_TWO_ID
    assert audits[0].resource_id == answer_id


async def test_feedback_without_a_reaction_only_records_adoption(
    postgres_client: AsyncClient,
) -> None:
    answer_id = await ask(postgres_client, MERCHANT_ONE_AUTH, "feedback-no-reaction-1")

    response = await postgres_client.post(
        f"/api/answers/{answer_id}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True},
    )

    assert response.status_code == 200
    assert response.json() == {"answer_id": answer_id, "is_adopted": True, "reaction": None}
