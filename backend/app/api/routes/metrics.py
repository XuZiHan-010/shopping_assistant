"""指标口径端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_merchant_context
from app.core.errors import ResourceNotFoundError, error_responses
from app.core.security import MerchantContext
from app.repositories.metric import MetricRepository
from app.schemas.chat import MetricDefinitionSource, MetricStatus
from app.schemas.metric import MetricDefinitionResponse

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics/{code}",
    response_model=MetricDefinitionResponse,
    # 路径参数 code 只是普通字符串，本身不会转换失败；但只要路由带路径参数，
    # FastAPI 就会自动挂上它自己的 HTTPValidationError 422 文档，不显式覆盖
    # 就会和 `ErrorResponse` 契约不一致（见 test_openapi_chat_contract.py）。
    responses=error_responses(401, 404, 422),
)
async def get_metric_definition(
    code: str,
    # 指标目录不按商家过滤，但口径属于产品资料，不对匿名访问开放，因此仍要求认证。
    _context: Annotated[MerchantContext, Depends(get_merchant_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MetricDefinitionResponse:
    """返回正式指标口径。指标目录对所有商家一致，因此不按商家过滤。"""

    definition = await MetricRepository(session).get_by_code_including_deprecated(code)
    if definition is None:
        raise ResourceNotFoundError("指标口径")
    return MetricDefinitionResponse(
        metric_code=definition.metric_code,
        display_name=definition.display_name,
        unit=definition.unit,
        definition=definition.business_definition,
        sql_definition=definition.sql_definition,
        dimensions=definition.dimensions,
        source_database=definition.source_database,
        source_table=definition.source_table,
        report_url=definition.report_url,
        source=MetricDefinitionSource(definition.source),
        generated=definition.generated,
        notice=definition.notice,
        owner=definition.owner,
        status=MetricStatus(definition.status),
    )
