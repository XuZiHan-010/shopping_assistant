"""统一业务异常与安全 API 错误格式。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from structlog.stdlib import BoundLogger


class ErrorCode(StrEnum):
    """对外错误码。

    这是后端实际会发出的错误码的唯一出处——不要在别处直写字符串字面量。
    每个成员都必须同时登记在 `docs/backend-development-plan.md` §14，
    否则前端按码查表渲染时会漏网（见 `docs/frontend-development-plan.md` §10）。

    后续阶段（B3 起的意图、查询、限流、附件等）按需扩充。
    """

    AUTH_REQUIRED = "AUTH_REQUIRED"
    MERCHANT_SCOPE_VIOLATION = "MERCHANT_SCOPE_VIOLATION"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    INVALID_REQUEST = "INVALID_REQUEST"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    REQUEST_IN_PROGRESS = "REQUEST_IN_PROGRESS"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorResponse(BaseModel):
    """对外稳定错误契约。"""

    code: ErrorCode
    message: str
    request_id: str
    details: list[dict[str, Any]] = Field(default_factory=list)
    retryable: bool = False


# 供 OpenAPI 声明使用的状态码描述。前端按 `code` 分支渲染（见前端方案 §10），
# 但先得能从契约里看出某条路由会发出哪些码——不声明就只能靠读后端源码。
_STATUS_DESCRIPTIONS: dict[int, str] = {
    401: "缺少或提供了无效的商家凭证",
    403: "越权访问其他商家资源",
    404: "资源不存在",
    405: "请求方法不被允许",
    409: "幂等键冲突或同一请求正在处理中",
    422: "请求参数不合法",
    429: "请求过于频繁",
    500: "服务内部错误",
    503: "依赖服务暂时不可用",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """生成路由的错误响应声明。

    显式声明 422 会阻止 FastAPI 自动注入它自己的 `HTTPValidationError`——
    我们的全局处理器返回的是 `ErrorResponse`，两者结构不同，不覆盖就等于
    契约在撒谎（`docs/backend-development-plan.md` §8.3）。
    """

    return {
        code: {
            "model": ErrorResponse,
            "description": _STATUS_DESCRIPTIONS[code],
        }
        for code in status_codes
    }


class AppError(Exception):
    """可安全映射为 API 响应的应用异常。"""

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        status_code: int,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.retryable = retryable


class DatabaseUnavailableError(AppError):
    """数据库暂时不可用。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.DATA_SOURCE_UNAVAILABLE,
            message="数据服务暂时不可用，请稍后重试",
            status_code=503,
            retryable=True,
        )


class AuthRequiredError(AppError):
    """缺少或提供了无效商家凭证。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.AUTH_REQUIRED,
            message="请提供有效的商家访问凭证",
            status_code=401,
        )


class MerchantScopeViolationError(AppError):
    """尝试访问其他商家的资源。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.MERCHANT_SCOPE_VIOLATION,
            message="无权访问该商家资源",
            status_code=403,
        )


class IdempotencyKeyReusedError(AppError):
    """同一幂等键不能对应不同请求内容。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.IDEMPOTENCY_KEY_REUSED,
            message="该请求标识已用于不同内容，请生成新的请求标识",
            status_code=409,
        )


class RequestInProgressError(AppError):
    """相同请求仍在处理，禁止并发重复执行。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.REQUEST_IN_PROGRESS,
            message="该请求正在处理中，请稍后重试",
            status_code=409,
            retryable=True,
        )


class ResourceNotFoundError(AppError):
    """商家范围内资源不存在。"""

    def __init__(self, resource_name: str) -> None:
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=f"{resource_name}不存在",
            status_code=404,
        )


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _response(error: ErrorResponse, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI, logger: BoundLogger) -> None:
    """注册全局异常处理器，禁止内部异常细节泄露给调用方。"""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _response(
            ErrorResponse(
                code=exc.code,
                message=exc.message,
                request_id=_request_id(request),
                details=exc.details,
                retryable=exc.retryable,
            ),
            exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": str(error["msg"]),
                "type": str(error["type"]),
            }
            for error in exc.errors()
        ]
        return _response(
            ErrorResponse(
                code=ErrorCode.INVALID_REQUEST,
                message="请求参数不合法",
                request_id=_request_id(request),
                details=details,
            ),
            422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            code, message = ErrorCode.NOT_FOUND, "请求的资源不存在"
        elif exc.status_code == 405:
            code, message = ErrorCode.METHOD_NOT_ALLOWED, "请求方法不被允许"
        else:
            code, message = ErrorCode.HTTP_ERROR, "请求处理失败"
        return _response(
            ErrorResponse(
                code=code,
                message=message,
                request_id=_request_id(request),
            ),
            exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_exception",
            request_id=_request_id(request),
            exception_type=type(exc).__name__,
        )
        return _response(
            ErrorResponse(
                code=ErrorCode.INTERNAL_ERROR,
                message="服务暂时不可用，请稍后重试",
                request_id=_request_id(request),
                retryable=True,
            ),
            500,
        )
