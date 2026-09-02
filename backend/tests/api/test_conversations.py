"""会话列表、详情与删除的 HTTP 契约测试。

跑在真实 PostgreSQL 上：§8.0 要求每条路由都有「未认证」和「跨商家越权」用例，
而越权必须同时写 audit_logs——用假 Repository 证明不了这一点。
"""

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.localization.locales import SupportedLocale, detect_source_language, hash_source_text
from app.models.answer import Answer
from app.models.conversation import Message
from app.models.operations import AuditLog
from app.prompts.localization import LOCALIZATION_PROMPT_VERSION
from app.repositories.conversation import ConversationRepository
from app.repositories.localization import LocalizationRepository
from tests.conftest import (
    MERCHANT_ONE_AUTH,
    MERCHANT_ONE_ID,
    MERCHANT_TWO_AUTH,
    MERCHANT_TWO_ID,
)

pytestmark = pytest.mark.asyncio


def _contains_han(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _collect_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for item in value.values():
            collected.extend(_collect_strings(item))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_collect_strings(item))
        return collected
    return []


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


async def test_detail_returns_redacted_assistant_payload_with_feedback_and_steps(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    """若移除详情装配或直接返回 JSONB，这条会分别漏字段或泄露敏感行。"""

    chat = await postgres_client.post(
        "/api/chat",
        headers={**MERCHANT_ONE_AUTH, "Accept": "application/json"},
        json={"message": "昨天总 GMV 是多少？", "client_request_id": "detail-payload-1"},
    )
    assert chat.status_code == 200
    answer_id = chat.json()["id"]
    conversation_id = chat.json()["session_id"]

    feedback = await postgres_client.post(
        f"/api/answers/{answer_id}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True, "reaction": "LIKE"},
    )
    assert feedback.status_code == 200

    async with postgres_app.state.database.session() as session:
        answer = await session.scalar(select(Answer).where(Answer.id == answer_id))
        assert answer is not None
        assert answer.response_payload is not None
        answer.response_payload = {
            **answer.response_payload,
            "data_rows": [{"order_no": "visible-column", "buyer_phone": "13800138000"}],
            "total_rows": 241,
            "truncated": True,
            "export": {
                "id": str(uuid4()),
                "url": "/api/exports/example?signature=must-not-leak",
                "expires_at": "2026-08-12T00:00:00Z",
            },
        }
        await session.commit()

    response = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )

    assert response.status_code == 200
    assistant = response.json()["messages"][1]
    payload = assistant["answer_payload"]
    assert payload["answer_id"] == answer_id
    assert payload["answer_mode"] == chat.json()["answer_mode"]
    assert payload["thinking_steps"] == chat.json()["thinking_steps"]
    assert payload["quality_status"] == chat.json()["quality_status"]
    assert payload["quality_attempts"] == chat.json()["quality_attempts"]
    assert payload["quality_notes"] == chat.json()["quality_notes"]
    assert payload["degraded"] == chat.json()["degraded"]
    assert payload["degraded_reason"] == chat.json()["degraded_reason"]
    assert payload["is_adopted"] is True
    assert payload["reaction"] == "LIKE"
    assert payload["columns"] == ["order_no", "buyer_phone"]
    assert payload["total_rows"] == 241
    assert payload["truncated"] is True
    assert "data_rows" not in payload
    assert "export" not in payload
    assert "13800138000" not in response.text
    assert "signature=" not in response.text


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


# ---------------------------------------------------------------------------
# Task 7（§8.6.3）：历史会话按页本地化、消息游标分页、按条目降级
# ---------------------------------------------------------------------------


async def _seed_messages(
    app: FastAPI,
    merchant_id: UUID,
    *,
    title: str,
    count: int,
) -> tuple[UUID, list[UUID]]:
    """直接写库造出一个只有纯文本消息的会话，跳过完整 Agent 流程——分页边界
    与本地化 payload 组装本身不依赖真实模型调用，绕开它能让测试更快、更少
    受"未配置真实 LLM 时具体回答内容是什么"这类无关因素影响。每条消息单独
    提交一次事务，避免 PostgreSQL `now()`在同一事务内保持不变导致时间戳并列。
    """

    async with app.state.database.session() as session:
        repository = ConversationRepository(session)
        conversation = await repository.create(merchant_id, title)
        await session.commit()
        conversation_id = conversation.id

    message_ids: list[UUID] = []
    for index in range(count):
        role = "USER" if index % 2 == 0 else "ASSISTANT"
        async with app.state.database.session() as session:
            repository = ConversationRepository(session)
            message = await repository.create_message(
                merchant_id, conversation_id, role, f"消息 {index}"
            )
            await session.commit()
            message_ids.append(message.id)
    return conversation_id, message_ids


async def test_conversation_detail_localizes_history_and_hides_source_han_text(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    """Task 7 Step 1（brief）核心失败示例：中文历史会话用英文请求查看时，
    可见文本里不应再出现任何汉字，且数据库里的原文必须原样保留。"""

    conversation_id = await start_conversation(
        postgres_client,
        MERCHANT_ONE_AUTH,
        message="最近7天退款金额",
        key="locale-detail-1",
    )

    response = await postgres_client.get(
        f"/api/conversations/{conversation_id}?message_limit=20",
        headers={**MERCHANT_ONE_AUTH, "Accept-Language": "en-US"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Language"] == "en-US"
    body = response.json()
    assert len(body["messages"]) <= 20
    assert not any(_contains_han(text) for text in _collect_strings(body))

    async with postgres_app.state.database.session() as session:
        original_content = await session.scalar(
            select(Message.content).where(
                Message.conversation_id == UUID(conversation_id),
                Message.role == "USER",
            )
        )
    assert original_content == "最近7天退款金额"


async def test_conversation_detail_cursor_pagination_serves_newest_page_first(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    conversation_id, message_ids = await _seed_messages(
        postgres_app, MERCHANT_ONE_ID, title="分页会话", count=7
    )

    first = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
        params={"message_limit": 5},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["messages"]) == 5
    assert first_body["has_more_messages"] is True
    assert first_body["next_message_cursor"] is not None

    second = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
        params={"message_limit": 5, "message_before": first_body["next_message_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert len(second_body["messages"]) == 2
    assert second_body["has_more_messages"] is False
    assert second_body["next_message_cursor"] is None

    all_ids = {message["id"] for message in first_body["messages"]} | {
        message["id"] for message in second_body["messages"]
    }
    assert all_ids == {str(message_id) for message_id in message_ids}


async def test_message_cursor_from_another_conversation_is_rejected(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    conversation_a_id, _ = await _seed_messages(
        postgres_app, MERCHANT_ONE_ID, title="会话 A", count=2
    )
    conversation_b_id, _ = await _seed_messages(
        postgres_app, MERCHANT_ONE_ID, title="会话 B", count=1
    )

    page = await postgres_client.get(
        f"/api/conversations/{conversation_a_id}",
        headers=MERCHANT_ONE_AUTH,
        params={"message_limit": 1},
    )
    cursor = page.json()["next_message_cursor"]
    assert cursor is not None

    response = await postgres_client.get(
        f"/api/conversations/{conversation_b_id}",
        headers=MERCHANT_ONE_AUTH,
        params={"message_before": cursor},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_message_cursor_from_another_merchant_is_rejected(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    conversation_id, _ = await _seed_messages(
        postgres_app, MERCHANT_ONE_ID, title="商家一的会话", count=2
    )
    other_conversation_id = await start_conversation(
        postgres_client, MERCHANT_TWO_AUTH, key="cursor-scope-own"
    )

    page = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
        params={"message_limit": 1},
    )
    cursor = page.json()["next_message_cursor"]
    assert cursor is not None

    response = await postgres_client.get(
        f"/api/conversations/{other_conversation_id}",
        headers=MERCHANT_TWO_AUTH,
        params={"message_before": cursor},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


async def test_conversation_list_flags_localization_degraded_when_title_cannot_translate(
    postgres_client: AsyncClient,
) -> None:
    conversation_id = await start_conversation(
        postgres_client,
        MERCHANT_ONE_AUTH,
        message="最近30天优惠券核销笔数",
        key="list-degraded-1",
    )

    response = await postgres_client.get(
        "/api/conversations",
        headers={**MERCHANT_ONE_AUTH, "Accept-Language": "en-US"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == conversation_id
    assert body["localization_degraded"] is True
    assert body["localization_degraded_reason"] is not None
    assert body["items"][0]["title"] == "Translation unavailable — retry"


async def test_translation_cache_resolves_independently_per_merchant_for_identical_content(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    """Task 7 Step 2：商家 B 请求自己的会话时，即使源文本与商家 A 的缓存
    字节相同，也必须按 B 自己的作用域重新解析，绝不能读到 A 的私有译文。"""

    source_text = "最近30天的复购率变化趋势说明"
    conversation_id = await start_conversation(
        postgres_client, MERCHANT_TWO_AUTH, message=source_text, key="cache-scope-1"
    )

    source_hash = hash_source_text(source_text)
    source_language = detect_source_language(source_text)
    async with postgres_app.state.database.session() as session:
        localization = LocalizationRepository(session)
        await localization.upsert_machine(
            merchant_id=MERCHANT_ONE_ID,
            source_hash=source_hash,
            source_language=source_language,
            target_locale=SupportedLocale.EN_US,
            translated_text="MERCHANT-A-PRIVATE-TRANSLATION",
            model="test-fixture",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await localization.upsert_machine(
            merchant_id=MERCHANT_TWO_ID,
            source_hash=source_hash,
            source_language=source_language,
            target_locale=SupportedLocale.EN_US,
            translated_text="MERCHANT-B-OWN-TRANSLATION",
            model="test-fixture",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await session.commit()

    response = await postgres_client.get(
        f"/api/conversations/{conversation_id}",
        headers={**MERCHANT_TWO_AUTH, "Accept-Language": "en-US"},
    )

    assert response.status_code == 200
    assert "MERCHANT-B-OWN-TRANSLATION" in response.text
    assert "MERCHANT-A-PRIVATE-TRANSLATION" not in response.text


async def test_deleting_a_conversation_purges_its_translation_cache_without_affecting_others(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    """Task 7 Step 6：删除会话把派生机器翻译缓存清理放进同一事务；哈希若同
    时被同一商家其它内容/别的商家复用，删除后应保持不受影响。"""

    source_text = "最近14天的商品上架数量趋势"
    conversation_id = await start_conversation(
        postgres_client, MERCHANT_ONE_AUTH, message=source_text, key="delete-cache-1"
    )

    source_hash = hash_source_text(source_text)
    source_language = detect_source_language(source_text)
    async with postgres_app.state.database.session() as session:
        localization = LocalizationRepository(session)
        await localization.upsert_machine(
            merchant_id=MERCHANT_ONE_ID,
            source_hash=source_hash,
            source_language=source_language,
            target_locale=SupportedLocale.EN_US,
            translated_text="Cached translation before deletion",
            model="test-fixture",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await localization.upsert_machine(
            merchant_id=MERCHANT_TWO_ID,
            source_hash=source_hash,
            source_language=source_language,
            target_locale=SupportedLocale.EN_US,
            translated_text="Merchant two keeps its own cache",
            model="test-fixture",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await session.commit()

    deleted = await postgres_client.delete(
        f"/api/conversations/{conversation_id}",
        headers=MERCHANT_ONE_AUTH,
    )
    assert deleted.status_code == 204

    async with postgres_app.state.database.session() as session:
        localization = LocalizationRepository(session)
        merchant_one_hits = await localization.get_merchant_machine_many(
            merchant_id=MERCHANT_ONE_ID,
            source_hashes=[source_hash],
            target_locale=SupportedLocale.EN_US,
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        merchant_two_hits = await localization.get_merchant_machine_many(
            merchant_id=MERCHANT_TWO_ID,
            source_hashes=[source_hash],
            target_locale=SupportedLocale.EN_US,
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )

    assert merchant_one_hits == {}
    assert merchant_two_hits[source_hash].translated_text == "Merchant two keeps its own cache"
