"""FastAPI 依赖注入。"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import BackgroundTasks, Depends, Request
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
from app.llm.client import LlmBudget, LlmClient
from app.llm.deepseek import DeepSeekLlmClient
from app.llm.fake import FakeLlmClient
from app.llm.guard import LlmCostGuard
from app.localization.locales import SupportedLocale, parse_accept_language
from app.metrics.catalog import MetricCatalog
from app.models.conversation import Conversation
from app.repositories.analytics import AnalyticsRepository
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.export import ExportRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.llm_budget import LlmBudgetRepository
from app.repositories.localization import LocalizationRepository
from app.repositories.memory import MerchantMemoryRepository
from app.repositories.merchant import MerchantRepository
from app.repositories.metric import MetricRepository
from app.services.chat_service import ChatService
from app.services.export_service import ExportService
from app.services.localization_service import LocalizationService
from app.services.memory_agent import MemoryAgent
from app.services.merchant_scope import MerchantScopeService
from app.services.report_service import DailyReportService
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


def get_request_locale(request: Request) -> SupportedLocale:
    """按当前请求的 `Accept-Language` 逐请求解析显示语言。

    不做全局缓存或 ContextVar：同一进程里不同请求的显示语言互不影响，
    每次都从这次请求自己的 Header 重新解析（`docs/backend-development-plan.md`
    §8.6.1）。
    """

    return parse_accept_language(request.headers.get("Accept-Language"))


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


def require_admin_or_viewer_token(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> None:
    """只读端点专用认证：管理员令牌或只读令牌任一匹配即放行。

    只挂在 GET 端点上——只读令牌本身可以公开展示，前提是它永远打不开任何写
    操作。挂错到写端点会让「只读」这个边界名存实亡，务必只在 `GET` 路由上使用。
    """

    token = request.headers.get("x-admin-token")
    if not token:
        raise AdminTokenRequiredError
    if settings.admin_token and hmac.compare_digest(token, settings.admin_token):
        return
    if settings.viewer_token and hmac.compare_digest(token, settings.viewer_token):
        return
    raise AdminForbiddenError


def build_guarded_llm(
    settings: Settings,
    database: Database,
    *,
    request_id: str,
    merchant_id: UUID | None,
    purpose: Literal["AGENT", "LOCALIZATION"] = "AGENT",
) -> LlmCostGuard:
    """构造带费用守卫的模型客户端。

    `merchant_id` 非空时必须是已确认存在的商家：它决定 token 用量与每日预算
    的归属，不能直接采信请求体（R5）。放宽为可空是为了给 `build_global_guarded_llm()`
    复用同一份构造逻辑——`llm_usage.merchant_id` 本身早已可空
    （`ForeignKey(..., ondelete="SET NULL")`），无商家上下文的调用写入 `NULL`
    并不破坏费用审计。
    """

    raw: LlmClient = (
        DeepSeekLlmClient(settings) if settings.llm_api_key else FakeLlmClient(configured=False)
    )
    return LlmCostGuard(
        raw,
        LlmBudgetRepository(database),
        settings,
        request_id=request_id,
        merchant_id=merchant_id,
        purpose=purpose,
    )


def build_global_guarded_llm(
    settings: Settings,
    database: Database,
    *,
    request_id: str,
) -> LlmCostGuard:
    """给无商家上下文的 `/api/admin/*` 全局调用（如 GLOBAL 作用域的本地化
    翻译）构造费用守卫；`merchant_id` 固定为 `None`，`purpose` 固定为
    `LOCALIZATION`——全局调用目前只有本地化通道会发生。"""

    return build_guarded_llm(
        settings,
        database,
        request_id=request_id,
        merchant_id=None,
        purpose="LOCALIZATION",
    )


async def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    background: BackgroundTasks,
) -> ChatService:
    """构造请求级 ChatService；B3 起由 MerchantQaGraph 处理问题。

    `merchant_id` 只能来自这里的 `MerchantContext`（FastAPI 按依赖函数缓存，
    不会因为路由已经解析过一次而多算一次认证）——绝不从请求体或查询参数取，
    那是可以被前端随意篡改的输入。
    """

    guard = build_guarded_llm(
        settings,
        database,
        request_id=str(request.state.request_id),
        merchant_id=context.merchant_id,
    )
    llm: LlmClient = guard
    conversations = ConversationRepository(session)
    merchant_summaries = await MerchantRepository(session).list_demo_by_ids([context.merchant_id])
    merchant_display = merchant_summaries[0].display_name if merchant_summaries else "商家"
    memory_repository = MerchantMemoryRepository(session)
    metric_repository = MetricRepository(session)
    localization_service, localization_budget = _build_localization_runtime(
        session,
        database,
        settings,
        request_id=str(request.state.request_id),
        merchant_id=context.merchant_id,
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(
            KnowledgeRepository(session),
            memories=memory_repository,
            merchant_id=context.merchant_id,
            metrics=metric_repository,
            all_memories=memory_repository,
            localizer=localization_service,
        ),
        intent_service_llm=llm,
        catalog=MetricCatalog(metric_repository, llm),
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
        history_questions=AnswerRepository(session),
        prefilter_enabled=settings.question_prefilter_enabled,
        prefilter_min_score=settings.question_prefilter_min_score,
        session_history=conversations,
        localization_budget=localization_budget,
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
        memory_agent=MemoryAgent(
            background=background,
            database=database,
            settings=settings,
            merchant_id=context.merchant_id,
            merchant_display=merchant_display,
            request_id=str(request.state.request_id),
        ),
        localization_service=localization_service,
        localization_budget=localization_budget,
    )


def _build_localization_runtime(
    session: AsyncSession,
    database: Database,
    settings: Settings,
    *,
    request_id: str,
    merchant_id: UUID,
) -> tuple[LocalizationService, LlmBudget]:
    """构造一次请求专用的本地化服务与共享预算。

    `purpose="LOCALIZATION"` 让 `llm_usage` 与 `purpose="AGENT"` 的主问答链路
    分开记账（复用 Task 4 已定的 `Settings.localization_max_calls_per_request`
    / `localization_max_tokens_per_request`）。返回的 `LlmBudget` 是
    per-request 对象，同一次调用内的多个消费点共享同一份预算，不同请求
    （包括 `POST /api/chat` 与 `GET /api/conversations*`）各自独立构造，互不
    挤占：

    - `POST /api/chat`：`ChatService`（`displayed_user_message`）与
      `MerchantQaGraph`（跨语言知识检索查询规范化）共享（Task 6）；
    - `GET /api/conversations` / `GET /api/conversations/{id}`：
      `app.localization.payloads.localize_conversation_summary()` /
      `localize_conversation_detail()` 各自在自己的请求内使用一份（Task 7）。
    """

    guard = build_guarded_llm(
        settings,
        database,
        request_id=request_id,
        merchant_id=merchant_id,
        purpose="LOCALIZATION",
    )
    service = LocalizationService(
        LocalizationRepository(session),
        guard,
        max_batch_items=settings.localization_max_batch_items,
        max_batch_chars=settings.localization_max_batch_chars,
        model=settings.llm_model,
    )
    budget = LlmBudget(
        settings.localization_max_calls_per_request,
        settings.localization_max_tokens_per_request,
    )
    return service, budget


async def get_conversation_localization(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
) -> tuple[LocalizationService, LlmBudget]:
    """`GET /api/conversations` / `GET /api/conversations/{id}` 专用的请求级
    本地化服务与预算（Task 7）。构造逻辑与 `get_chat_service()` 内部使用的
    完全一致（见 `_build_localization_runtime()`），只是这里是独立的 FastAPI
    依赖，供两个只读会话历史路由直接 `Depends()`。"""

    return _build_localization_runtime(
        session,
        database,
        settings,
        request_id=str(request.state.request_id),
        merchant_id=context.merchant_id,
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


def get_daily_report_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DailyReportService:
    """日报不使用 LLM；只装配受控经营数据与会话持久化依赖。"""

    return DailyReportService(
        session,
        ConversationRepository(session),
        AnalyticsRepository(session),
        business_timezone=settings.business_timezone,
    )


def get_conversation_scope_service(
    conversations: Annotated[ConversationRepository, Depends(get_conversation_repository)],
    database: Annotated[Database, Depends(get_database)],
) -> MerchantScopeService[Conversation]:
    return MerchantScopeService(conversations, AuditRepository(database))
