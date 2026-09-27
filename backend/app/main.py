"""FastAPI 应用工厂。"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import admin_routers, api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.metrics import OperationalMetrics
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.session import Database
from app.knowledge.wiki_seed import seed_wiki_documents
from app.localization.locales import parse_accept_language
from app.services.session_reconciliation import reconcile_demo_issuers
from app.skills.registry import DEFAULT_ROOTS, SkillRegistry
from app.skills.tool import skill_tools
from app.tools.customer import build_customer_tools
from app.tools.merchant import build_merchant_tools
from app.tools.registry import build_tool_registry

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# 跨域放行的请求头。商家 Bearer 走 Authorization，管理员走 X-Admin-Token，
# v2 顾客/商家会话走 X-Session-Id，后端据此区分调用方，详见 AGENTS.md §八。
_ALLOWED_HEADERS = [
    "Authorization",
    "X-Admin-Token",
    "X-Session-Id",
    "Accept",
    "Content-Type",
    "X-Request-Id",
]


def _resolve_request_id(value: str | None) -> str:
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


RequestHandler = Callable[[Request], Awaitable[Response]]


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
) -> FastAPI:
    """创建可注入配置的 FastAPI 应用。"""

    resolved_settings = settings or get_settings()
    logger = configure_logging(resolved_settings)
    resolved_database = database or Database(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await resolved_database.connect_with_retry()
            # 先于其他启动任务执行，且失败即中止启动：对账没跑成，被移除的演示
            # Token 换出的商家会话就仍然有效，宁可起不来也不带着这个缺口对外服务。
            revoked = await reconcile_demo_issuers(resolved_database, resolved_settings)
            logger.info("session_issuers_reconciled", revoked_sessions=revoked)
            created = await seed_wiki_documents(resolved_database)
            logger.info("wiki_seed_imported", created=created)
            yield
        finally:
            # 连接、对账或种子导入失败也必须释放连接池。
            await resolved_database.dispose()

    app = FastAPI(
        title="Borough 商家 AI 助手 API",
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.logger = logger
    app.state.database = resolved_database
    app.state.rate_limiter = SlidingWindowRateLimiter(
        resolved_settings.rate_limit_per_minute, clock=monotonic
    )
    app.state.metrics = OperationalMetrics()
    # 工具注册表自检在这里执行：错误的工具定义让服务起不来，而不是在某次提问时才暴露（§6.9）。
    # N2 模块 C 登记商家工具面，`n2-trade-closed-loop` Task 6 登记顾客工具面；两面互不相交。
    # Skill 注册表同样在启动期扫描白名单目录并自检（PRD A4）：格式、长度或路径不合格让服务起不来。
    # 索引非空的角色才会得到 `load_skill` 工具；两端都为空时工具面与 N2 相同。
    app.state.skill_registry = SkillRegistry.from_roots(
        DEFAULT_ROOTS, max_chars=resolved_settings.skill_max_chars
    )
    app.state.tool_registry = build_tool_registry(
        (
            *build_merchant_tools(
                resolved_database,
                business_timezone=resolved_settings.business_timezone,
                alias_secret=(
                    resolved_settings.buyer_alias_secret or "development-buyer-alias-secret"
                ).encode(),
                export_signing_secret=resolved_settings.export_signing_secret,
                export_url_ttl_minutes=resolved_settings.export_url_ttl_minutes,
            ),
            *build_customer_tools(resolved_database),
            *skill_tools(app.state.skill_registry),
        )
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=_ALLOWED_HEADERS,
        max_age=600,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: RequestHandler) -> Response:
        request_id = _resolve_request_id(request.headers.get("X-Request-Id"))
        request.state.request_id = request_id
        # 同一个中间件顺带回显显示语言：`call_next` 返回的是应用层（含
        # AppError/校验/404 等已注册异常处理器）解析完的 Response，这些
        # 路径都会正常流经这里。**但完全没有处理器匹配的未预期异常
        # （500）不会**——它只被 Starlette 最外层的 `ServerErrorMiddleware`
        # 捕获，比这个中间件本身还要外一层，`call_next()` 在这种情况下会
        # 直接向上抛出而不是返回，下面这段收尾代码根本执行不到。所以 500
        # 这条路径的 `Content-Language`/`Vary` 由
        # `app.core.errors._response()` 在响应创建时自己打上，不能只靠
        # 这里兜底（`docs/backend-development-plan.md` §8.6.1
        # 「错误响应也必须经过相同 Header 注入」）。
        locale = parse_accept_language(request.headers.get("Accept-Language"))
        start = monotonic()
        response = await call_next(request)
        duration_seconds = monotonic() - start
        route = request.scope.get("route")
        route_path = route.path if route is not None else request.url.path
        if route is not None and request.url.path.startswith("/api/"):
            # `include_router(..., prefix="/api")` 的子路由只保留自身模板；
            # 日志和运维快照仍应按对外 API 模板聚合，避免遗漏父级前缀。
            route_path = f"/api{route_path}"
        app.state.metrics.record_route_duration(route_path, duration_seconds)
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            route=route_path,
            status_code=response.status_code,
            duration_ms=round(duration_seconds * 1000, 2),
        )
        response.headers["X-Request-Id"] = request_id
        response.headers["Content-Language"] = locale.value
        existing_vary = response.headers.get("Vary")
        vary_values = [value.strip() for value in existing_vary.split(",")] if existing_vary else []
        if "Accept-Language" not in vary_values:
            vary_values.append("Accept-Language")
        response.headers["Vary"] = ", ".join(vary_values)
        return response

    register_exception_handlers(app, logger)
    app.include_router(api_router, prefix="/api")
    if resolved_settings.admin_token:
        for admin_router in admin_routers:
            app.include_router(admin_router, prefix="/api")
    return app
