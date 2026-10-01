"""明细导出工具（N3 阶段 C Task 5，PRD M7，Astra N3-4 必审）。

只有一个工具 `create_export`：`READ_ONLY`——它只建一条导出记录和一个限时签名链接，
**不返回任何一行明细数据**，导出范围（商家、时间、行数上限）全部由 `ExportService`/
`AnalyticsRepository` 在后端强制（R4）。创建与下载分别审计：创建审计 `EXPORT_CREATED`
写在这里，下载审计 `EXPORT_DOWNLOADED` 写在 `app/api/routes/exports.py`（签名校验通过、
内容生成成功后才写；v1 既有路径，v2 复用同一签名链接）。

**`answer_id` 恒为 `None`**：这个工具在工具循环执行期间运行，此时本轮的 `Answer` 行
尚未落库（`services/v2/merchant_chat.py` 在循环结束后才写 `Answer`）；`ExportFile`
用独立事务立即提交，传入一个此刻还不存在的外键值会导致约束冲突。`export_files.answer_id`
已放宽为可空（迁移 `20260925_0036`），v2 导出的访问控制完全由 `merchant_id` 承担，
`answer_id` 只是 v1 遗留的溯源字段，v2 路径没有它一样安全。
"""

from __future__ import annotations

from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analytics.contract import detail_spec
from app.db.session import Database
from app.repositories.analytics import MAX_EXPORT_ROWS, AnalyticsRepository
from app.repositories.audit import AuditRepository
from app.repositories.export import ExportRepository
from app.services.export_service import ExportService
from app.services.safe_query import ExportSpec
from app.tools.errors import GuardrailRejection
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy

#: 五类导出（PRD M7）：订单、订单明细、退款、退货、工单——与受控明细白名单一一对应，
#: 不暴露 `products`（商品明细不属于 M7 范围，且导出商品会绕过内容 Skill 的审批流程）。
EXPORT_KINDS: Final = ("orders", "order_items", "refunds", "returns", "support_tickets")
EXPORT_CREATED_EVENT: Final = "EXPORT_CREATED"
#: 本地/测试环境未配置 `EXPORT_SIGNING_SECRET` 时的兜底，与 `api/dependencies.py` 一致；
#: 生产环境由 `Settings.enforce_environment_safety` 强制要求真实值。
_DEV_EXPORT_SIGNING_SECRET: Final = "development-export-signing-secret"


class CreateExportArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(" + "|".join(EXPORT_KINDS) + ")$")
    start: date
    end: date

    @model_validator(mode="after")
    def bounded_dates(self) -> CreateExportArgs:
        if self.end < self.start or (self.end - self.start).days > 89:
            raise ValueError("导出日期须递增且最多覆盖 90 天")
        return self


def build_export_tools(
    database: Database,
    audit: AuditRepository,
    *,
    signing_secret: str | None,
    export_url_ttl_minutes: int,
) -> tuple[ToolSpec, ...]:
    secret = signing_secret or _DEV_EXPORT_SIGNING_SECRET

    async def create_export(ctx: ToolContext, args: CreateExportArgs) -> ToolOutput:
        spec = detail_spec(args.kind)
        export_spec = ExportSpec(
            table=spec.table,
            columns=tuple(name for name, _ in spec.columns),
            start=args.start,
            end=args.end,
            date_filtered=spec.date_filtered,
        )
        async with database.session() as session:
            analytics = AnalyticsRepository(session)
            total_rows = await analytics.count_export_detail(
                merchant_id=ctx.session.merchant_id,
                spec=spec,
                start=args.start,
                end=args.end,
            )
            if total_rows > MAX_EXPORT_ROWS:
                raise GuardrailRejection(
                    code="EXPORT_ROW_LIMIT",
                    current_limit=f"符合条件 {total_rows} 行；同步导出上限 {MAX_EXPORT_ROWS} 行",
                    remediation="请缩小导出日期范围后重试",
                )
            service = ExportService(
                ExportRepository(session),
                analytics,
                signing_secret=secret,
                ttl_minutes=export_url_ttl_minutes,
            )
            info = await service.create(
                merchant_id=ctx.session.merchant_id, answer_id=None, spec=export_spec,
                locale=ctx.locale,
            )
            await session.commit()
        # 独立事务写审计（与业务提交分开，见 AuditRepository 模块说明）。
        await audit.record_event(
            merchant_id=ctx.session.merchant_id,
            event_type=EXPORT_CREATED_EVENT,
            resource_type="EXPORT",
            resource_id=str(info.id),
            request_id=ctx.request_id,
        )
        return ToolOutput(
            payload={
                "export_id": str(info.id),
                "url": info.url,
                "expires_at": info.expires_at.isoformat(),
                "kind": args.kind,
                "total_rows": total_rows,
                "current_rows": total_rows,
                "limit_reached": total_rows == MAX_EXPORT_ROWS,
            },
            # 摘要不带任何行数据——即使工具结果被围栏进模型上下文，也没有明细可读。
            summary=f"已创建{spec.label}导出，下载链接有效期至 {info.expires_at.isoformat()}",
            row_count=None,
        )

    return (
        ToolSpec(
            name="create_export",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=CreateExportArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=False,
            description=(
                "创建一份经营明细导出（订单、订单明细、退款、退货或工单），"
                "返回限时下载链接；不会把任何一行明细数据带回对话。"
            ),
            executor=create_export,
        ),
    )
