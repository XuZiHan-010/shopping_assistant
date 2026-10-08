"""商品内容草稿处理器（N3 阶段 C Task 3，PRD M4、D11）。

第 5–7 步：目标基数（`content_version`）复检 → 条件写入商品属性/描述 → 内容版本 +1。
没有护栏复检——商品内容没有金额/库存类的业务护栏，唯一的约束（属性值三来源、
待补属性不由模型补全）在起草阶段（`tools/merchant/content.py`）就已经强制，
不是需要在应用时按"当时生效配置"复检的那类会随时间变化的规则。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidRequestError, VersionConflictError
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.analytics import Product
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from app.services.v2.drafts import content_change_entry_id

#: 起草时只接受这三种来源（D11①）；处理器写入前再核对一次，防止绕过起草侧校验的
#: 数据（例如直接构造草稿行）被应用。
_ALLOWED_SOURCE_TYPES: Final = frozenset(
    {"MERCHANT_FILLED", "MERCHANT_STATED", "DESCRIPTION_EXTRACT"}
)


class ContentChangeHandler:
    kind: DraftKind = DraftKind.CONTENT_CHANGE

    async def apply(
        self,
        session: AsyncSession,
        ctx: SessionContext,
        draft: Draft,
        request: HandlerRequest,
        *,
        now: datetime,
        locale: SupportedLocale,
    ) -> HandlerResult:
        del locale
        entry_id = content_change_entry_id(draft)
        if request.accepted_entry_ids is not None and set(request.accepted_entry_ids) != {
            entry_id
        }:
            raise InvalidRequestError(
                details=[{"field": "accepted_entry_ids", "reason": "UNKNOWN_ENTRY"}]
            )
        if request.target_version != draft.target_version:
            raise VersionConflictError(scope="TARGET")

        attributes = cast("dict[str, dict[str, Any]]", draft.payload["attributes"])
        for name, entry in attributes.items():
            if entry.get("source_type") not in _ALLOWED_SOURCE_TYPES:
                raise InvalidRequestError(
                    details=[{"field": f"attributes.{name}.source_type", "reason": "INVALID"}]
                )

        merged_attributes = dict(draft.payload.get("base_attributes", {}))
        for name, entry in attributes.items():
            # 写回商品记录时保持 Mapping 结构（value/source/source_type/source_ref），
            # 不能只存裸字符串——`_attribute_values()`（顾客工具）与本地化服务
            # （`app/services/v2/catalog.py`）读取同一字段时都按 Mapping 解析，拍扁成
            # 字符串会让两处都把这个属性当成"缺失"（2026-09-26 修复，S2 场景 e2e 测试发现）。
            # 三种起草来源都是商家在本轮对话或商品记录里确认过的真实内容，统一记为
            # 本地化服务的 `source="MERCHANT"`（需要翻译），不是 `"DEMO"`。
            merged_attributes[name] = {
                "value": entry["value"],
                "source": "MERCHANT",
                "source_type": entry["source_type"],
                "source_ref": entry.get("source_ref"),
            }

        values: dict[str, Any] = {
            "attributes": merged_attributes,
            "content_version": Product.content_version + 1,
        }
        if "short_description" in draft.payload:
            values["short_description"] = draft.payload["short_description"]
        if "detail_description" in draft.payload:
            values["detail_description"] = draft.payload["detail_description"]

        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(Product)
                .where(
                    Product.id == draft.target_id,
                    Product.merchant_id == ctx.merchant_id,
                    Product.content_version == draft.target_version,
                )
                .values(**values)
            ),
        )
        if result.rowcount != 1:
            raise VersionConflictError(scope="TARGET")
        del now
        return HandlerResult(checks=[], applied_entry_ids=[entry_id])
