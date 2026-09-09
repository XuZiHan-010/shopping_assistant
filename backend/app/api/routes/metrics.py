"""指标口径端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_merchant_context, get_request_locale
from app.core.errors import ResourceNotFoundError, error_responses
from app.core.security import MerchantContext
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale
from app.repositories.metric import MetricRepository
from app.schemas.chat import MetricDefinitionSource, MetricStatus
from app.schemas.metric import MetricDefinitionResponse

router = APIRouter(tags=["metrics"])


def _localized(value: str, locale: SupportedLocale) -> str:
    """指标口径的展示名/单位/业务定义/负责人整句均出自
    `app.localization.catalog` 已登记的闭集词典（`analytics/contract.py` 的
    `METRIC_SPECS`/`metrics/seed.py` 的 `METRIC_SEED`/`metrics/field_comments.py`
    的字段注释）——零 LLM。词典未命中（如测试自建的非受控指标口径）原样返回，
    不静默报错，也不为口径面板触发真实模型调用。"""

    return localize_catalog_value(value, locale) or value


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
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> MetricDefinitionResponse:
    """返回正式指标口径。指标目录对所有商家一致，因此不按商家过滤。"""

    definition = await MetricRepository(session).get_by_code_including_deprecated(code)
    if definition is None:
        raise ResourceNotFoundError("指标口径")
    return MetricDefinitionResponse(
        metric_code=definition.metric_code,
        display_name=_localized(definition.display_name, locale),
        unit=_localized(definition.unit, locale),
        definition=_localized(definition.business_definition, locale),
        sql_definition=definition.sql_definition,
        dimensions=definition.dimensions,
        source_database=definition.source_database,
        source_table=definition.source_table,
        report_url=definition.report_url,
        source=MetricDefinitionSource(definition.source),
        generated=definition.generated,
        notice=_localized(definition.notice, locale) if definition.notice else definition.notice,
        owner=_localized(definition.owner, locale),
        status=MetricStatus(definition.status),
    )
