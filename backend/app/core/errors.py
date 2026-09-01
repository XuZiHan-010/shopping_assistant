"""统一业务异常与安全 API 错误格式。"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from structlog.stdlib import BoundLogger

from app.localization.error_messages import (
    localize_error_message,
    localize_validation_detail_message,
)
from app.localization.locales import SupportedLocale, parse_accept_language


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
    DAILY_REPORT_FEEDBACK_CONFLICT = "DAILY_REPORT_FEEDBACK_CONFLICT"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    EXPORT_LINK_EXPIRED = "EXPORT_LINK_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    LLM_BUDGET_EXCEEDED = "LLM_BUDGET_EXCEEDED"
    FORBIDDEN = "FORBIDDEN"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_WIKI_PATH = "INVALID_WIKI_PATH"
    WIKI_READ_ONLY = "WIKI_READ_ONLY"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    INVALID_WIKI_PARENT = "INVALID_WIKI_PARENT"
    WIKI_NODE_EXISTS = "WIKI_NODE_EXISTS"
    WIKI_NODE_NOT_FOUND = "WIKI_NODE_NOT_FOUND"
    WIKI_DIRECTORY_NOT_EMPTY = "WIKI_DIRECTORY_NOT_EMPTY"
    WIKI_VERSION_REQUIRED = "WIKI_VERSION_REQUIRED"
    WIKI_VERSION_CONFLICT = "WIKI_VERSION_CONFLICT"
    WIKI_DOCUMENT_TOO_LARGE = "WIKI_DOCUMENT_TOO_LARGE"
    INVALID_WIKI_ENCODING = "INVALID_WIKI_ENCODING"
    INVALID_WIKI_CONTENT = "INVALID_WIKI_CONTENT"
    WIKI_IO_ERROR = "WIKI_IO_ERROR"


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
    400: "请求内容不符合业务规则",
    401: "缺少或提供了无效的商家凭证",
    403: "无权访问该资源或管理端点",
    404: "资源不存在",
    405: "请求方法不被允许",
    409: "幂等键冲突或同一请求正在处理中",
    412: "资源已被其他维护者更新",
    413: "请求内容超过允许大小",
    415: "请求内容编码不受支持",
    428: "请求缺少条件版本",
    410: "导出链接已过期",
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
    """可安全映射为 API 响应的应用异常。

    `message` 只是内部默认文案与日志上下文——各调用点历史上传入的中文
    句子仍然保留在这里，但**不会**被异常处理器直接放进响应体。对外展示
    的 `message` 一律由 `message_params` 经 `localize_error_message()`
    按当前请求 `Accept-Language` 渲染，因为同一个 `code` 可能被多处不同
    业务复用（例如 `ResourceNotFoundError` 的 `resource_name` 因调用点而
    异），无法只靠 `code` 反推正确的双语文案。
    """

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        status_code: int,
        details: list[dict[str, Any]] | None = None,
        retryable: bool = False,
        message_params: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.retryable = retryable
        self.message_params: dict[str, Any] = dict(message_params) if message_params else {}


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
            message_params={"audience": "merchant"},
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


class DailyReportFeedbackConflictError(AppError):
    """已被商家反馈引用的日报不得被重算替换。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.DAILY_REPORT_FEEDBACK_CONFLICT,
            message="该日报已有商家反馈，不能重算替换",
            status_code=409,
        )


class InvalidRequestError(AppError):
    """请求在语法正确后仍违反受控业务边界。"""

    def __init__(self, message: str = "请求参数不合法") -> None:
        super().__init__(
            code=ErrorCode.INVALID_REQUEST,
            message=message,
            status_code=422,
        )


class ResourceNotFoundError(AppError):
    """商家范围内资源不存在。"""

    def __init__(self, resource_name: str) -> None:
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=f"{resource_name}不存在",
            status_code=404,
            message_params={"resource_name": resource_name},
        )


class ExportLinkExpiredError(AppError):
    """签名正确但已经超过有效期的导出链接。"""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.EXPORT_LINK_EXPIRED,
            message="导出链接已过期，请重新发起查询后下载",
            status_code=410,
        )


class RateLimitedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.RATE_LIMITED,
            message="请求过于频繁，请稍后重试",
            status_code=429,
            retryable=True,
        )


class DailyBudgetExhaustedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.LLM_BUDGET_EXCEEDED,
            message="今日模型用量已达上限，请稍后重试",
            status_code=503,
            retryable=True,
        )


class AdminTokenRequiredError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.AUTH_REQUIRED,
            message="请提供有效的管理员凭证",
            status_code=401,
            message_params={"audience": "admin"},
        )


class AdminForbiddenError(AppError):
    def __init__(self) -> None:
        super().__init__(code=ErrorCode.FORBIDDEN, message="无管理员权限", status_code=403)


class KnowledgeAdminError(AppError):
    """知识库维护接口的受控错误。"""

    def __init__(self, code: ErrorCode, message: str, status_code: int) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _request_locale(request: Request) -> SupportedLocale:
    """独立于 `get_request_locale` 依赖重新解析一遍。

    异常处理器不经过 FastAPI 的依赖注入流水线，只拿得到 `Request`；这里
    直接复用同一个纯函数 `parse_accept_language`，与
    `app.api.dependencies.get_request_locale` 对同一个 Header 的解析结果
    保持一致，不引入第二套判定逻辑。
    """

    return parse_accept_language(request.headers.get("Accept-Language"))


def _response(error: ErrorResponse, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI, logger: BoundLogger) -> None:
    """注册全局异常处理器，禁止内部异常细节泄露给调用方。

    对外展示的 `message` 一律按当前请求的 `Accept-Language` 渲染
    （`docs/backend-development-plan.md` §8.6.1）；`Content-Language` /
    `Vary` 响应头由 `app.main` 里的中间件统一注入，这里不重复处理。
    """

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request.app.state.metrics.record_error_code(str(exc.code))
        locale = _request_locale(request)
        return _response(
            ErrorResponse(
                code=exc.code,
                message=localize_error_message(exc.code, exc.message_params, locale),
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
        locale = _request_locale(request)
        details = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": localize_validation_detail_message(str(error["type"]), locale),
                "type": str(error["type"]),
            }
            for error in exc.errors()
        ]
        return _response(
            ErrorResponse(
                code=ErrorCode.INVALID_REQUEST,
                message=localize_error_message(ErrorCode.INVALID_REQUEST, None, locale),
                request_id=_request_id(request),
                details=details,
            ),
            422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        locale = _request_locale(request)
        if exc.status_code == 404:
            code = ErrorCode.NOT_FOUND
        elif exc.status_code == 405:
            code = ErrorCode.METHOD_NOT_ALLOWED
        else:
            code = ErrorCode.HTTP_ERROR
        return _response(
            ErrorResponse(
                code=code,
                message=localize_error_message(code, None, locale),
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
        locale = _request_locale(request)
        return _response(
            ErrorResponse(
                code=ErrorCode.INTERNAL_ERROR,
                message=localize_error_message(ErrorCode.INTERNAL_ERROR, None, locale),
                request_id=_request_id(request),
                retryable=True,
            ),
            500,
        )
