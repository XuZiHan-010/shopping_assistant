"""受控经营数据查询。

三条不可协商的规则：

1. 表名和列名只能来自 `app.analytics.contract` 的注册表，绝不来自入参字符串；
2. 每条查询都强制 `merchant_id` 过滤，没有「查全部商家」的入口；
3. 所有值参数走 SQLAlchemy 绑定，不做字符串拼接。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import (
    DetailSpec,
    DimensionSpec,
    MetricSpec,
    UnknownFieldError,
    dimension_spec,
)
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket

# 值类型写成 type[Any]：这些 ORM 类各自的列集合不同，取公共父类会丢掉列信息；
# 反正后续都是按 contract 里登记的列名 getattr，不需要静态精确到具体子类。
_TABLES: Mapping[str, type[Any]] = {
    "orders": Order,
    "order_items": OrderItem,
    "products": Product,
    "refunds": Refund,
    "returns": ReturnRecord,
    "support_tickets": SupportTicket,
}


@dataclass(frozen=True)
class ResultColumn:
    key: str
    label: str
    kind: Literal["DIMENSION", "METRIC"]


@dataclass(frozen=True)
class AggregateResult:
    columns: tuple[ResultColumn, ...]
    rows: list[dict[str, object]]
    source_tables: tuple[str, ...]


@dataclass(frozen=True)
class DetailResult:
    columns: tuple[ResultColumn, ...]
    rows: list[dict[str, object]]
    total_rows: int
    truncated: bool
    source_tables: tuple[str, ...]


def _order_identity(*, via_order_items: bool) -> ColumnElement[Any]:
    """`orders` 行标识列：join 展开成多行时必须 distinct，否则同一张订单

    会被同一分组里的多个订单项数出多次。
    """

    return cast("ColumnElement[Any]", func.distinct(Order.id) if via_order_items else Order.id)


def _metric_expression(metric: MetricSpec, *, via_order_items: bool = False) -> ColumnElement[Any]:
    """`via_order_items` 为真时说明本次查询为了拿 `product`/`category` 维度，

    已经把 `orders` join 到了 `order_items`/`products`——这会让 `orders` 的行
    按订单项展开。此时金额类指标必须改成对 `order_items.item_amount` 求和
    （把整单金额按订单项分摊到各类目/商品，这才是「按类目拆 GMV」本该有的
    口径），计数类指标必须改成 `count(distinct orders.id)`（避免同一张订单
    因为落在同一分组里的多个订单项被数出多次）。不需要该维度时保持原口径，
    不为了统一实现而牺牲已经验证过的默认路径。
    """

    if metric.code == "gmv":
        amount_column = OrderItem.item_amount if via_order_items else Order.paid_amount
        return func.sum(amount_column).filter(
            Order.order_status.in_(("PAID", "SHIPPED", "COMPLETED"))
        )
    if metric.code == "order_count":
        return func.count(_order_identity(via_order_items=via_order_items))
    if metric.code == "paying_user_count":
        # distinct(buyer_key) 按值去重，不按行去重，join 展开不会放大它。
        return func.count(func.distinct(Order.buyer_key)).filter(Order.paid_at.is_not(None))
    if metric.code == "successful_order_count":
        return func.count(_order_identity(via_order_items=via_order_items)).filter(
            Order.order_status == "COMPLETED"
        )
    if metric.code == "refund_count":
        return func.count(Refund.id).filter(Refund.refund_status.in_(("APPROVED", "REFUNDED")))
    if metric.code == "refund_amount":
        return func.sum(Refund.refund_amount).filter(Refund.refund_status == "REFUNDED")
    if metric.code == "return_count":
        return func.sum(ReturnRecord.return_quantity)
    if metric.code == "support_ticket_count":
        return func.count(SupportTicket.id)
    raise AssertionError(f"未实现的指标表达式：{metric.code}")


def _needs_products_join(specs: Sequence[DimensionSpec], filters: Mapping[str, str]) -> bool:
    """维度或筛选条件里，有没有一个落在 `products` 表上。"""

    needed = {spec.table for spec in specs if spec.table} | {
        dimension_spec(code).table for code in filters if dimension_spec(code).table
    }
    return "products" in needed


def _dimension_column(metric: MetricSpec, spec: DimensionSpec) -> ColumnElement[Any]:
    # _TABLES 的值类型是 type[Any]：getattr/属性访问天然返回 Any，
    # 显式 cast 回 ColumnElement 只是把「这是一列」的事实告诉 mypy。
    if spec.code == "date":
        # date 用主表自己的业务日列；RATIO 指标的主表是分母所在的 order_items。
        return cast("ColumnElement[Any]", _TABLES[metric.table].business_date)
    return cast("ColumnElement[Any]", getattr(_TABLES[spec.table], spec.column))


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def aggregate(
        self,
        *,
        merchant_id: UUID,
        metric: MetricSpec,
        dimensions: Sequence[str],
        filters: Mapping[str, str],
        start: date,
        end: date,
        limit: int,
        sort: str | None = None,
    ) -> AggregateResult:
        if metric.kind == "RATIO":
            return await self._aggregate_ratio(
                merchant_id=merchant_id,
                metric=metric,
                dimensions=dimensions,
                filters=filters,
                start=start,
                end=end,
                limit=limit,
                sort=sort,
            )

        table = _TABLES[metric.table]
        specs = [dimension_spec(code) for code in dimensions]
        group_columns = [_dimension_column(metric, spec) for spec in specs]
        # 只有「orders 主表 + 需要 join 到 products」这条路径会被 join 展开；
        # order_items/refunds/returns/support_tickets 各自的指标本就以自己
        # 的行为聚合粒度，不会因为这条 join 产生重复计数。
        via_order_items = metric.table == "orders" and _needs_products_join(specs, filters)

        metric_column = _metric_expression(metric, via_order_items=via_order_items).label(
            metric.code
        )
        statement: Select[Any] = select(
            *[column.label(spec.code) for column, spec in zip(group_columns, specs, strict=True)],
            metric_column,
        ).where(
            table.merchant_id == merchant_id,
            table.business_date >= start,
            table.business_date <= end,
        )
        statement = self._join_dimensions(statement, metric, specs, filters)
        statement = self._apply_filters(statement, metric, filters)
        if group_columns:
            statement = statement.group_by(*group_columns).limit(limit)
            statement = statement.order_by(
                *self._order_by(metric_column, metric, specs, group_columns, sort)
            )

        result = await self._session.execute(statement)
        rows = [dict(row) for row in result.mappings()]
        return AggregateResult(
            columns=self._columns(metric, specs),
            rows=rows,
            source_tables=self._source_tables(
                metric, specs, filters, via_order_items=via_order_items
            ),
        )

    async def detail(
        self,
        *,
        merchant_id: UUID,
        spec: DetailSpec,
        filters: Mapping[str, str],
        start: date,
        end: date,
        limit: int,
    ) -> DetailResult:
        """预览有上限，总数照实报——只给 200 行却说「共 200 条」是撒谎。

        明细查询不 join 维度表：筛选条件只对落在 `spec.table` 自身的维度生效，
        跨表的维度会被忽略而不是报错。这是当前已知的窄口——真正校验筛选与
        目标明细表是否兼容，应该在调用方（意图解析/路由层）完成。
        """

        table = _TABLES[spec.table]
        columns = [getattr(table, name) for name, _ in spec.columns]
        conditions = [
            table.merchant_id == merchant_id,
            table.business_date >= start,
            table.business_date <= end,
        ]
        for code, value in filters.items():
            dimension = dimension_spec(code)
            if dimension.table == spec.table:
                conditions.append(getattr(table, dimension.column) == value)

        total = await self._session.scalar(
            select(func.count()).select_from(table).where(*conditions)
        )
        preview = await self._session.execute(
            select(*columns)
            .where(*conditions)
            .order_by(table.business_date.desc(), table.id)
            .limit(limit)
        )
        rows = [dict(row) for row in preview.mappings()]
        total_rows = int(total or 0)
        return DetailResult(
            columns=tuple(ResultColumn(name, label, "DIMENSION") for name, label in spec.columns),
            rows=rows,
            total_rows=total_rows,
            truncated=total_rows > len(rows),
            source_tables=(spec.table,),
        )

    async def _aggregate_ratio(
        self,
        *,
        merchant_id: UUID,
        metric: MetricSpec,
        dimensions: Sequence[str],
        filters: Mapping[str, str],
        start: date,
        end: date,
        limit: int,
        sort: str | None = None,
    ) -> AggregateResult:
        """比例指标按区间重算，绝不按日均求平均。

        先把 returns 按 order_item_id 聚合再 LEFT JOIN，避免一个订单项有多条
        退货记录时把分母（订单项件数）重复计入。
        """

        returns_agg = (
            select(
                ReturnRecord.order_item_id.label("order_item_id"),
                func.sum(ReturnRecord.return_quantity).label("returned_quantity"),
            )
            .where(ReturnRecord.merchant_id == merchant_id)
            .group_by(ReturnRecord.order_item_id)
            .subquery()
        )
        specs = [dimension_spec(code) for code in dimensions]
        group_columns = [_dimension_column(metric, spec) for spec in specs]
        ratio = (
            func.sum(func.coalesce(returns_agg.c.returned_quantity, 0))
            / func.nullif(func.sum(OrderItem.quantity), 0)
        ).label(metric.code)

        statement: Select[Any] = (
            select(
                *[
                    column.label(spec.code)
                    for column, spec in zip(group_columns, specs, strict=True)
                ],
                ratio,
            )
            .select_from(OrderItem)
            .outerjoin(returns_agg, returns_agg.c.order_item_id == OrderItem.id)
            .where(
                OrderItem.merchant_id == merchant_id,
                OrderItem.business_date >= start,
                OrderItem.business_date <= end,
            )
        )
        statement = self._join_dimensions(statement, metric, specs, filters)
        statement = self._apply_filters(statement, metric, filters)
        if group_columns:
            statement = statement.group_by(*group_columns).limit(limit)
            statement = statement.order_by(
                *self._order_by(ratio, metric, specs, group_columns, sort)
            )

        result = await self._session.execute(statement)
        return AggregateResult(
            columns=self._columns(metric, specs),
            rows=[dict(row) for row in result.mappings()],
            source_tables=("order_items", "returns"),
        )

    def _order_by(
        self,
        metric_column: ColumnElement[Any],
        metric: MetricSpec,
        specs: Sequence[DimensionSpec],
        group_columns: Sequence[ColumnElement[Any]],
        sort: str | None,
    ) -> Sequence[ColumnElement[Any]]:
        """排序键只能指向本次查询已经 SELECT 出来的列对象。

        这里**不做任何字符串拼接**：`sort` 只用来在已有的列对象里挑一个，挑不中
        就抛错。默认按维度升序——趋势图要的是时间顺序，不是数值顺序。
        """

        if not sort:
            return list(group_columns)

        descending = sort.startswith("-")
        key = sort.lstrip("-")
        if key == metric.code:
            ordering = metric_column
        else:
            matched = [
                column
                for column, spec in zip(group_columns, specs, strict=True)
                if spec.code == key
            ]
            if not matched:
                raise UnknownFieldError(f"排序键 {sort} 不在本次查询的列内")
            ordering = matched[0]
        return [ordering.desc() if descending else ordering.asc()]

    def _join_dimensions(
        self,
        statement: Select[Any],
        metric: MetricSpec,
        specs: Sequence[DimensionSpec],
        filters: Mapping[str, str],
    ) -> Select[Any]:
        """按需连接维度表。连接路径写死在代码里，不由入参决定。"""

        if _needs_products_join(specs, filters) and metric.table in {"orders", "order_items"}:
            if metric.table == "orders":
                statement = statement.join(OrderItem, OrderItem.order_id == Order.id)
            statement = statement.join(Product, Product.id == OrderItem.product_id)
        return statement

    def _apply_filters(
        self,
        statement: Select[Any],
        metric: MetricSpec,
        filters: Mapping[str, str],
    ) -> Select[Any]:
        for code, value in filters.items():
            spec = dimension_spec(code)
            column = _dimension_column(metric, spec)
            # value 走绑定参数；它是数据，永远不参与 SQL 结构。
            statement = statement.where(column == value)
        return statement

    def _columns(
        self, metric: MetricSpec, specs: Sequence[DimensionSpec]
    ) -> tuple[ResultColumn, ...]:
        return (
            *[ResultColumn(spec.code, spec.label, "DIMENSION") for spec in specs],
            ResultColumn(metric.code, metric.label, "METRIC"),
        )

    def _source_tables(
        self,
        metric: MetricSpec,
        specs: Sequence[DimensionSpec],
        filters: Mapping[str, str],
        *,
        via_order_items: bool = False,
    ) -> tuple[str, ...]:
        tables = {metric.table}
        if via_order_items:
            # 金额类指标改成对 order_items.item_amount 求和之后，
            # order_items 是实际参与聚合的表，如实报出来。
            tables.add("order_items")
        tables |= {spec.table for spec in specs if spec.table}
        tables |= {dimension_spec(code).table for code in filters if dimension_spec(code).table}
        return tuple(sorted(tables))
