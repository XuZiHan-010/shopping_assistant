"""v2 幂等写入的通用守卫（契约 §8.7.3）：白名单端点复用同一套判定，不各自发明。

唯一域固定为 `role + principal_digest + merchant_id + operation + client_request_id`；
`request_digest` 只取规范化后的业务输入。状态、请求摘要、终态响应与业务写入必须落在
同一数据库事务——本模块不在内部提交，提交时机由调用路由决定（与 v1 Chat 幂等一致）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.errors import AppError, ErrorCode, IdempotencyKeyReusedError, RequestInProgressError
from app.core.session import SessionContext
from app.core.session import principal_digest as session_principal_digest
from app.models.idempotency import IdempotencyRecord
from app.repositories.v2.idempotency import IdempotencyRepository
from app.tools.errors import FatalToolError


async def run_idempotent(
    *,
    repo: IdempotencyRepository,
    ctx: SessionContext,
    secret: bytes,
    operation: str,
    client_request_id: str,
    request_digest: str,
    response_status: int,
    execute: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """按 §8.7.3 判定并执行一次幂等写入，返回可直接回放的响应体。

    `execute()` 只负责做实际业务写入并把响应序列化为 dict；本函数负责幂等记录的
    创建、冲突判定与终态写回，两者的先后顺序保证同一事务里"业务写入"与"记录终态"
    要么都发生要么都不发生。
    """

    digest = session_principal_digest(ctx, secret=secret)
    existing = await repo.find(
        role=ctx.role.value,
        principal_digest=digest,
        merchant_id=ctx.merchant_id,
        operation=operation,
        client_request_id=client_request_id,
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise IdempotencyKeyReusedError
        if existing.status == "SUCCEEDED":
            assert existing.response_body is not None
            return existing.response_body
        if existing.status == "PROCESSING":
            raise RequestInProgressError
        if existing.status == "FAILED_FINAL":
            assert existing.response_body is not None
            raise AppError(
                code=ErrorCode(existing.response_body["code"]),
                message="已记录的不可重试错误",
                status_code=existing.response_status or 403,
                message_params=existing.response_body.get("message_params", {}),
            )
        # FAILED_RETRYABLE：允许原地重跑，复用同一条记录而不是新建一条。
        record = existing
    else:
        candidate = IdempotencyRecord.from_session(
            ctx,
            secret=secret,
            operation=operation,
            client_request_id=client_request_id,
            request_digest=request_digest,
        )
        created = await repo.try_create_processing(candidate)
        if created is None:
            # 并发请求抢先插入了同一条记录：退回按"已存在"分支处理。
            raced = await repo.find(
                role=ctx.role.value,
                principal_digest=digest,
                merchant_id=ctx.merchant_id,
                operation=operation,
                client_request_id=client_request_id,
            )
            if raced is None or raced.request_digest != request_digest:
                raise IdempotencyKeyReusedError
            if raced.status == "SUCCEEDED":
                assert raced.response_body is not None
                return raced.response_body
            if raced.status == "FAILED_FINAL":
                assert raced.response_body is not None
                raise AppError(
                    code=ErrorCode(raced.response_body["code"]),
                    message="已记录的不可重试错误",
                    status_code=raced.response_status or 403,
                    message_params=raced.response_body.get("message_params", {}),
                )
            raise RequestInProgressError
        record = created

    try:
        body = await execute()
    except FatalToolError as exc:
        await repo.mark_failed(
            record,
            retryable=False,
            response_status=exc.status_code,
            response_body={"code": exc.code.value, "message_params": exc.message_params},
        )
        raise
    except Exception:
        await repo.mark_failed(record, retryable=True)
        raise
    await repo.mark_succeeded(record, response_status=response_status, response_body=body)
    return body
