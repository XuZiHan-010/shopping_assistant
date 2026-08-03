from dataclasses import dataclass, field
from uuid import UUID

import pytest

from app.core.errors import MerchantScopeViolationError, ResourceNotFoundError
from app.core.security import MerchantContext
from app.services.merchant_scope import MerchantScopeService

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000002")
CONVERSATION_ID = UUID("10000000-0000-0000-0000-000000000001")


@dataclass(frozen=True)
class ConversationRecord:
    id: UUID
    merchant_id: UUID


@dataclass
class FakeConversationRepository:
    conversation: ConversationRecord | None

    async def get_for_merchant(
        self, conversation_id: UUID, merchant_id: UUID
    ) -> ConversationRecord | None:
        if (
            self.conversation
            and self.conversation.id == conversation_id
            and self.conversation.merchant_id == merchant_id
        ):
            return self.conversation
        return None

    async def exists(self, conversation_id: UUID) -> bool:
        return bool(self.conversation and self.conversation.id == conversation_id)


@dataclass
class FakeAuditRepository:
    events: list[dict[str, object]] = field(default_factory=list)

    async def record_scope_violation(
        self,
        *,
        actor_merchant_id: UUID,
        resource_type: str,
        resource_id: str,
        request_id: str,
    ) -> None:
        self.events.append(
            {
                "actor_merchant_id": actor_merchant_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "request_id": request_id,
            }
        )


@pytest.mark.asyncio
async def test_same_merchant_can_access_conversation() -> None:
    conversation = ConversationRecord(CONVERSATION_ID, MERCHANT_ONE_ID)
    audits = FakeAuditRepository()
    service = MerchantScopeService(
        FakeConversationRepository(conversation),
        audits,
    )

    result = await service.require_conversation(
        MerchantContext(merchant_id=MERCHANT_ONE_ID),
        CONVERSATION_ID,
        request_id="request-1",
    )

    assert result == conversation
    assert audits.events == []


@pytest.mark.asyncio
async def test_cross_merchant_access_is_forbidden_and_audited() -> None:
    conversation = ConversationRecord(CONVERSATION_ID, MERCHANT_TWO_ID)
    audits = FakeAuditRepository()
    service = MerchantScopeService(
        FakeConversationRepository(conversation),
        audits,
    )

    with pytest.raises(MerchantScopeViolationError):
        await service.require_conversation(
            MerchantContext(merchant_id=MERCHANT_ONE_ID),
            CONVERSATION_ID,
            request_id="request-2",
        )

    assert audits.events == [
        {
            "actor_merchant_id": MERCHANT_ONE_ID,
            "resource_type": "conversation",
            "resource_id": str(CONVERSATION_ID),
            "request_id": "request-2",
        }
    ]


@pytest.mark.asyncio
async def test_missing_conversation_is_not_reported_as_scope_violation() -> None:
    audits = FakeAuditRepository()
    service = MerchantScopeService(FakeConversationRepository(None), audits)

    with pytest.raises(ResourceNotFoundError):
        await service.require_conversation(
            MerchantContext(merchant_id=MERCHANT_ONE_ID),
            CONVERSATION_ID,
            request_id="request-3",
        )

    assert audits.events == []
