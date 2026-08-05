"""FastAPI 依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import MerchantQaGraph
from app.core.config import Settings
from app.core.errors import AuthRequiredError
from app.core.security import MerchantContext, resolve_demo_token
from app.db.session import Database
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.client import LlmClient
from app.llm.deepseek import DeepSeekLlmClient
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.models.conversation import Conversation
from app.repositories.analytics import AnalyticsRepository
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.merchant import MerchantRepository
from app.repositories.metric import MetricRepository
from app.services.chat_service import ChatService
from app.services.merchant_scope import MerchantScopeService
from app.services.safe_query import SafeQueryService

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


def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
) -> ChatService:
    """构造请求级 ChatService；B3 起由 MerchantQaGraph 处理问题。

    `merchant_id` 只能来自这里的 `MerchantContext`（FastAPI 按依赖函数缓存，
    不会因为路由已经解析过一次而多算一次认证）——绝不从请求体或查询参数取，
    那是可以被前端随意篡改的输入。
    """

    llm: LlmClient = (
        DeepSeekLlmClient(settings) if settings.llm_api_key else FakeLlmClient(configured=False)
    )
    conversations = ConversationRepository(session)
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(KnowledgeRepository(session)),
        intent_service_llm=llm,
        catalog=MetricCatalog(MetricRepository(session), llm),
        max_llm_calls=settings.llm_max_calls_per_request,
        max_llm_tokens=settings.llm_max_tokens_per_request,
        query_service=SafeQueryService(
            AnalyticsRepository(session), business_timezone=settings.business_timezone
        ),
        merchant_id=context.merchant_id,
    )
    return ChatService(
        session,
        conversations,
        graph,
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
