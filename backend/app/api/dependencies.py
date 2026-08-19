"""FastAPI 依赖注入。"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import MerchantQaGraph
from app.core.client_ip import resolve_client_ip
from app.core.config import Settings
from app.core.errors import (
    AdminForbiddenError,
    AdminTokenRequiredError,
    AuthRequiredError,
    RateLimitedError,
)
from app.core.security import MerchantContext, resolve_demo_token
from app.db.session import Database
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.client import LlmClient
from app.llm.deepseek import DeepSeekLlmClient
from app.llm.fake import FakeLlmClient
from app.llm.guard import LlmCostGuard
from app.metrics.catalog import MetricCatalog
from app.models.conversation import Conversation
from app.repositories.analytics import AnalyticsRepository
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.export import ExportRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.llm_budget import LlmBudgetRepository
from app.repositories.merchant import MerchantRepository
from app.repositories.metric import MetricRepository
from app.services.chat_service import ChatService
from app.services.export_service import ExportService
from app.services.merchant_scope import MerchantScopeService
from app.services.safe_query import SafeQueryService

_bearer = HTTPBearer(auto_error=False)

# 仅用于本地/测试环境未配置 EXPORT_SIGNING_SECRET 时的兜底；生产环境由
# `Settings.enforce_environment_safety` 强制要求真实值，这个常量永远不会在
# 生产路径上被使用。
_DEV_EXPORT_SIGNING_SECRET = "development-export-signing-secret"


def _build_export_service(session: AsyncSession, settings: Settings) -> ExportService:
    return ExportService(
        ExportRepository(session),
        AnalyticsRepository(session),
        signing_secret=settings.export_signing_secret or _DEV_EXPORT_SIGNING_SECRET,
        ttl_minutes=settings.export_url_ttl_minutes,
    )


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


def enforce_rate_limit(
    request: Request,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    token = request.headers.get("authorization", "")
    limiter = request.app.state.rate_limiter
    if not limiter.allow(
        token=token,
        client_ip=resolve_client_ip(
            request,
            trusted_proxy_hops=settings.trusted_proxy_hops,
            trusted_proxy_ips=settings.trusted_proxy_ip_set,
        ),
    ):
        request.app.state.metrics.rate_limit_hits += 1
        raise RateLimitedError


def require_admin_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    """运维端点专用认证：只认 `X-Admin-Token`，忽略 `Authorization`。"""

    token = request.headers.get("x-admin-token")
    if not token:
        raise AdminTokenRequiredError
    if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
        raise AdminForbiddenError


def get_chat_service(
    request: Request,
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

    raw_llm: LlmClient = (
        DeepSeekLlmClient(settings) if settings.llm_api_key else FakeLlmClient(configured=False)
    )
    guard = LlmCostGuard(
        raw_llm,
        LlmBudgetRepository(database),
        settings,
        request_id=str(request.state.request_id),
        merchant_id=context.merchant_id,
    )
    llm: LlmClient = guard
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
        answer_llm=llm,
        reviewer_llm=llm,
        quality_max_attempts=settings.quality_max_attempts,
        node_timer=request.app.state.metrics,
    )
    return ChatService(
        session,
        conversations,
        graph,
        MerchantScopeService(conversations, AuditRepository(database)),
        _build_export_service(session, settings),
        guard,
        guard,
        metrics=request.app.state.metrics,
    )


def get_export_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ExportService:
    return _build_export_service(session, settings)


def get_conversation_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConversationRepository:
    return ConversationRepository(session)


def get_conversation_scope_service(
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    database: Annotated[Database, Depends(get_database)],
) -> MerchantScopeService[Conversation]:
    return MerchantScopeService(conversations, AuditRepository(database))
