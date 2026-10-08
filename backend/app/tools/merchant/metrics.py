"""业绩洞察与归因工具（N3 阶段 C Task 1，PRD M3、S5）。

两个工具都是 `READ_ONLY`：只查询、不写任何业务事实。模型只能提交结构化参数
（指标码、维度、日期范围），归因的分项贡献、占比/绝对值的选择、周期对比全部由
`AttributionService` 用确定性代码算出（R4）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.analytics.contract import METRIC_SPECS
from app.core.security import MerchantContext
from app.db.session import Database
from app.repositories.analytics import AnalyticsRepository
from app.services.safe_query import SafeQueryService, UnsupportedQueryError
from app.services.v2.attribution import AttributionService, ChartPointLimitExceeded
from app.services.v2.visualization import (
    build_visualization_for_attribution,
    build_visualization_for_series,
)
from app.tools.errors import FatalToolError
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy

#: 归因目前只开放按类目下钻，与 v1 `DIMENSION_SPECS` 一致（`app/analytics/contract.py`）。
_ATTRIBUTION_DIMENSIONS = ("category",)


class QueryMetricsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=64)
    start: date
    end: date

    def validate_metric(self) -> None:
        if self.metric != "net_gmv" and self.metric not in METRIC_SPECS:
            raise ValueError(f"指标 {self.metric} 不在可查询范围内")


class AttributeChangeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(
        min_length=1,
        max_length=64,
        description="受控指标机器码；净成交额使用 net_gmv，毛成交额使用 gross_gmv。",
    )
    dimension: str = Field(default="category", min_length=1, max_length=32)


def build_metrics_tools(database: Database, *, business_timezone: str) -> tuple[ToolSpec, ...]:
    async def query_metrics(ctx: ToolContext, args: QueryMetricsArgs) -> ToolOutput:
        if args.metric != "net_gmv" and args.metric not in METRIC_SPECS:
            raise FatalToolError(
                gate="unknown_metric", tool_name="query_metrics", detail=f"未知指标 {args.metric}"
            )
        async with database.session() as session:
            service = AttributionService(
                SafeQueryService(AnalyticsRepository(session), business_timezone=business_timezone)
            )
            merchant = MerchantContext(merchant_id=ctx.session.merchant_id)
            now = datetime.now(UTC)
            try:
                result = await service.query_metrics(
                    merchant, metric=args.metric, start=args.start, end=args.end, now=now,
                )
                # 图表要的是逐日序列，不是这个方法算出的单个汇总值；额外查一次序列，
                # 不复用上面的结果——两者查询形状不同（标量聚合 vs. 按 date 分组），
                # 复用需要重构查询层，本次先接受多一次查询的代价（PRD M3、契约 §8.7.11）。
                series = await service.query_metrics_series(
                    merchant, metric=args.metric, start=args.start, end=args.end, now=now,
                )
            except UnsupportedQueryError as error:
                raise FatalToolError(
                    gate="unsupported_query", tool_name="query_metrics", detail=str(error)
                ) from error
            except ChartPointLimitExceeded:
                # 图表点数超限不该拖垮原本能成功的单值查询——退回"无图表"，
                # 单值结果照常返回；模型仍能引用数字，只是本次没有可画的趋势图。
                series = None
        visualization = (
            build_visualization_for_series(series, metric=args.metric)
            if series is not None
            else None
        )
        return ToolOutput(
            payload={
                "metric": args.metric,
                "value": str(result.value) if result.value is not None else None,
                "data_cutoff": result.data_cutoff.isoformat(),
                "source": result.source.value,
                "definition_version": result.definition_version,
            },
            summary=f"{args.metric} 在 {args.start} 至 {args.end} 的查询已完成",
            row_count=1 if result.value is not None else 0,
            chart_data=visualization,
        )

    async def attribute_change(ctx: ToolContext, args: AttributeChangeArgs) -> ToolOutput:
        if args.metric != "net_gmv" and args.metric not in METRIC_SPECS:
            raise FatalToolError(
                gate="unknown_metric",
                tool_name="attribute_change",
                detail=f"未知指标 {args.metric}",
            )
        if args.dimension not in _ATTRIBUTION_DIMENSIONS:
            raise FatalToolError(
                gate="unsupported_dimension",
                tool_name="attribute_change",
                detail=f"暂不支持按「{args.dimension}」归因",
            )
        async with database.session() as session:
            service = AttributionService(
                SafeQueryService(AnalyticsRepository(session), business_timezone=business_timezone)
            )
            now = datetime.now(UTC)
            try:
                result = await service.attribute_change(
                    MerchantContext(merchant_id=ctx.session.merchant_id),
                    metric=args.metric,
                    dimension=args.dimension,
                    now=now,
                    business_timezone=business_timezone,
                )
            except ChartPointLimitExceeded as error:
                raise FatalToolError(
                    gate="chart_point_limit", tool_name="attribute_change", detail=str(error)
                ) from error
        if result.stopped:
            return ToolOutput(
                payload={
                    "stopped": True, "reason": result.stopped_reason, "segments": [],
                    "data_cutoff": result.data_cutoff.isoformat(),
                    "source": result.source.value,
                    "definition_version": result.definition_version,
                },
                summary=result.stopped_reason or "归因因数据缺口而停止",
                row_count=0,
                chart_data=build_visualization_for_attribution(result, metric=args.metric),
            )
        return ToolOutput(
            payload={
                "stopped": False,
                "mode": result.mode,
                "comparison": list(result.comparison_label),
                "data_cutoff": result.data_cutoff.isoformat(),
                "source": result.source.value,
                "definition_version": result.definition_version,
                "segments": [
                    {
                        "name": segment.name,
                        "current_value": str(segment.current_value),
                        "baseline_value": str(segment.baseline_value),
                        "share": str(segment.share) if segment.share is not None else None,
                        "absolute_contribution": str(segment.absolute_contribution),
                    }
                    for segment in result.segments
                ],
            },
            summary=f"已按「{args.dimension}」完成 {args.metric} 的归因分析",
            row_count=len(result.segments),
            chart_data=build_visualization_for_attribution(result, metric=args.metric),
        )

    return (
        ToolSpec(
            name="query_metrics",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=QueryMetricsArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description=(
                "查询单个经营指标在指定日期范围内的数值，返回数据截至时间、数据来源"
                "（实时/日汇总/混合）与指标定义版本。"
            ),
            executor=query_metrics,
        ),
        ToolSpec(
            name="attribute_change",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=AttributeChangeArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description=(
                "对某个指标本周至今与上周同等长度区间做归因分析，按维度拆分贡献。"
                "整体变化明显时给出各细分占比，接近零或正负抵消时改报绝对贡献值。"
            ),
            executor=attribute_change,
        ),
    )
