"""商家资源授权与越权审计。"""

from __future__ import annotations

from uuid import UUID

from app.core.errors import MerchantScopeViolationError, ResourceNotFoundError
from app.core.security import MerchantContext
from app.repositories.protocols import (
    AuditRepositoryProtocol,
    ConversationLookupProtocol,
)


class MerchantScopeService[ConversationT]:
    def __init__(
        self,
        conversations: ConversationLookupProtocol[ConversationT],
        audits: AuditRepositoryProtocol,
    ) -> None:
        self._conversations = conversations
        self._audits = audits

    async def require_conversation(
        self,
        context: MerchantContext,
        conversation_id: UUID,
        *,
        request_id: str,
    ) -> ConversationT:
        """返回本商家会话；跨商家探测只记录最小审计信息。"""

        conversation = await self._conversations.get_for_merchant(
            conversation_id,
            context.merchant_id,
        )
        if conversation is not None:
            return conversation

        if await self._conversations.exists(conversation_id):
            await self._audits.record_scope_violation(
                actor_merchant_id=context.merchant_id,
                resource_type="conversation",
                resource_id=str(conversation_id),
                request_id=request_id,
            )
            raise MerchantScopeViolationError

        raise ResourceNotFoundError("会话")
