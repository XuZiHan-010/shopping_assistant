"""Repository 稳定协议。"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar
from uuid import UUID

ConversationT = TypeVar("ConversationT", covariant=True)


class ConversationLookupProtocol(Protocol[ConversationT]):
    async def get_for_merchant(
        self,
        conversation_id: UUID,
        merchant_id: UUID,
    ) -> ConversationT | None: ...

    async def exists(self, conversation_id: UUID) -> bool: ...


class AuditRepositoryProtocol(Protocol):
    async def record_scope_violation(
        self,
        *,
        actor_merchant_id: UUID,
        resource_type: str,
        resource_id: str,
        request_id: str,
    ) -> None: ...

    async def record_event(
        self,
        *,
        merchant_id: UUID | None,
        event_type: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        request_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...
