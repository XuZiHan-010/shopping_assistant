"""并发插入争用后，终态回放须与普通已存在路径一致。"""

from unittest.mock import AsyncMock

import pytest

from app.core.errors import AppError, ErrorCode
from app.models.idempotency import IdempotencyRecord
from app.repositories.v2.idempotency import IdempotencyRepository
from app.services.v2.idempotency import run_idempotent
from tests.unit.tools.tool_doubles import customer_session


@pytest.mark.asyncio
async def test_concurrent_loser_replays_failed_final_instead_of_in_progress() -> None:
    ctx = customer_session()
    record = IdempotencyRecord.from_session(
        ctx,
        secret=b"test-secret",
        operation="shop.chat",
        client_request_id="same",
        request_digest="same-digest",
    )
    record.status = "FAILED_FINAL"
    record.response_status = 403
    record.response_body = {"code": "RESOURCE_FORBIDDEN", "message_params": {}}
    repo = AsyncMock(spec=IdempotencyRepository)
    repo.find.side_effect = [None, record]
    repo.try_create_processing.return_value = None

    async def execute() -> dict[str, object]:
        pytest.fail("终态回放不得重新执行写操作")

    with pytest.raises(AppError) as error:
        await run_idempotent(
            repo=repo,
            ctx=ctx,
            secret=b"test-secret",
            operation="shop.chat",
            client_request_id="same",
            request_digest="same-digest",
            response_status=200,
            execute=execute,
        )

    assert error.value.code is ErrorCode.RESOURCE_FORBIDDEN
    assert error.value.status_code == 403
