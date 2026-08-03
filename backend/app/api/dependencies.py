"""FastAPI 依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.fake_agent import FakeAgent
from app.core.config import Settings
from app.core.errors import AuthRequiredError
from app.core.security import MerchantContext, resolve_demo_token
from app.db.session import Database
from app.models.conversation import Conversation
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.merchant import MerchantRepository
from app.services.chat_service import ChatService
from app.services.merchant_scope import MerchantScopeService

_bearer = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database = get_database(request)
    async with database.session() as session:
        yield session


def get_merchant_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MerchantRepository:
    return MerchantRepository(session)


def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
) -> ChatService:
    """构造请求级 ChatService；B2 固定使用不联网的 Fake Agent。"""

    conversations = ConversationRepository(session)
    return ChatService(
        session,
        conversations,
        FakeAgent(),
        MerchantScopeService(conversations, AuditRepository(database)),
    )


def get_conversation_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationRepository:
    return ConversationRepository(session)


def get_conversation_scope_service(
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    database: Annotated[Database, Depends(get_database)],
) -> MerchantScopeService[Conversation]:
    return MerchantScopeService(conversations, AuditRepository(database))


def get_merchant_context(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer),
    ],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> MerchantContext:
    """商家认证依赖，只接受服务端配置的 Bearer Token。"""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthRequiredError
    return resolve_demo_token(credentials.credentials, settings)
