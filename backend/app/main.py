"""FastAPI 应用工厂。"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.admin import router as admin_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.metrics import OperationalMetrics
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.session import Database

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# 跨域放行的请求头。两套凭证走两个不同的头：商家用 Authorization，
# 管理员用 X-Admin-Token，后端据此区分调用方，详见 AGENTS.md §10.2.1。
_ALLOWED_HEADERS = [
    "Authorization",
    "X-Admin-Token",
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
        except Exception as exc:
            logger.warning(
                "database_startup_degraded",
                exception_type=type(exc).__name__,
            )
        yield
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(resolved_settings.frontend_origin).rstrip("/")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=_ALLOWED_HEADERS,
        max_age=600,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: RequestHandler) -> Response:
        request_id = _resolve_request_id(request.headers.get("X-Request-Id"))
        request.state.request_id = request_id
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
        return response

    register_exception_handlers(app, logger)
    app.include_router(api_router, prefix="/api")
    if resolved_settings.admin_token:
        app.include_router(admin_router, prefix="/api")
    return app
