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

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import (
    DetailSpec,
    DimensionSpec,
    MetricSpec,
    UnknownFieldError,
    dimension_spec,
)
from app.intent.models import CrossBusinessPlan, CrossBusinessPlanType, GeneratedMetricPlan
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.schemas.chat import QuestionCategory

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

    async def _fetch_with_total(
        self,
        statement: Select[Any],
        *,
        limit: int | None,
        columns: tuple[ResultColumn, ...],
        source_tables: tuple[str, ...],
        known_total: int | None = None,
    ) -> DetailResult:
        """执行明细/生成指标查询共用的收尾：数总数 → 加 LIMIT → 取数据 → 拼结果。

        `known_total` 供调用方在明知结果只有一行时跳过额外的 COUNT 子查询
        （例如无 GROUP BY 的聚合，SQL 语义上必然恰好一行），避免每次热路径
        查询多打一次数据库往返。
        """

        if known_total is None:
            total = await self._session.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            total_rows = int(total or 0)
        else:
            total_rows = known_total
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        rows = [dict(row) for row in result.mappings()]
        return DetailResult(
            columns=columns,
            rows=rows,
            total_rows=total_rows,
            truncated=total_rows > len(rows),
            source_tables=source_tables,
        )

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

    async def generated_metric(
        self,
        *,
        merchant_id: UUID,
        category: QuestionCategory,
        plan: GeneratedMetricPlan,
        start: date,
        end: date,
        limit: int | None,
    ) -> DetailResult:
        """执行临时分组指标的类别驱动固定模板。

        ``GeneratedMetricPlan`` 只能决定两种已登记的维度是否出现；指标表达式、
        join、筛选列和排序全在这里固定，永远不接受 LLM 给出的列名、公式或 SQL。
        """

        if category is QuestionCategory.TRADE:
            return await self._generated_trade_metric(
                merchant_id=merchant_id,
                plan=plan,
                start=start,
                end=end,
                limit=limit,
            )
        if category is QuestionCategory.REFUND:
            return await self._generated_refund_metric(
                merchant_id=merchant_id,
                plan=plan,
                start=start,
                end=end,
                limit=limit,
            )
        raise ValueError("generated metric category is not supported")

    async def _generated_trade_metric(
        self,
        *,
        merchant_id: UUID,
        plan: GeneratedMetricPlan,
        start: date,
        end: date,
        limit: int | None,
    ) -> DetailResult:
        # 已付款状态必须在 WHERE 里过滤，不能只放进各聚合列自己的 FILTER 子句：
        # 分组场景下，一个 SPU/城市若只有取消/待支付订单，FILTER-only 仍会让
        # GROUP BY 为它产出一行全零/NULL 的噪音记录，污染预览、导出和总数统计。
        order_count = func.count(func.distinct(Order.id)).label("order_count")
        order_user_count = func.count(func.distinct(Order.buyer_key)).label("order_user_count")
        quantity = func.sum(OrderItem.quantity).label("quantity")
        paid_amount = func.sum(OrderItem.item_amount).label("paid_amount")
        metrics = (order_count, order_user_count, quantity, paid_amount)
        statement: Select[Any] = (
            select(*metrics)
            .select_from(Order)
            .join(
                OrderItem,
                and_(OrderItem.order_id == Order.id, OrderItem.merchant_id == merchant_id),
            )
            .join(
                Product,
                and_(Product.id == OrderItem.product_id, Product.merchant_id == merchant_id),
            )
            .where(
                Order.merchant_id == merchant_id,
                Order.business_date >= start,
                Order.business_date <= end,
                Order.order_status.in_(("PAID", "SHIPPED", "COMPLETED")),
            )
        )
        statement = self._apply_generated_filter(statement, plan)
        group_columns, dimensions = self._generated_dimensions(plan)
        if group_columns:
            statement = (
                statement.with_only_columns(*dimensions, *metrics)
                .group_by(*group_columns)
                .order_by(order_count.desc(), paid_amount.desc())
            )
        return await self._fetch_with_total(
            statement,
            # 无 GROUP BY 时 SQL 语义上恰好一行（聚合函数总有返回值），不必
            # 另发一次 COUNT 子查询去问一个已知答案。
            limit=limit if group_columns else None,
            known_total=None if group_columns else 1,
            columns=(
                *self._generated_result_columns(plan),
                *self._trade_generated_metric_columns(),
            ),
            source_tables=("orders", "order_items", "products"),
        )

    async def _generated_refund_metric(
        self,
        *,
        merchant_id: UUID,
        plan: GeneratedMetricPlan,
        start: date,
        end: date,
        limit: int | None,
    ) -> DetailResult:
        refund_count = func.count(func.distinct(Refund.id)).label("refund_count")
        refund_user_count = func.count(func.distinct(Order.buyer_key)).label("refund_user_count")
        refund_amount = func.sum(Refund.refund_amount).label("refund_amount")
        metrics = (refund_count, refund_user_count, refund_amount)
        statement: Select[Any] = (
            select(*metrics)
            .select_from(Refund)
            .join(
                OrderItem,
                and_(OrderItem.id == Refund.order_item_id, OrderItem.merchant_id == merchant_id),
            )
            .join(Order, and_(Order.id == OrderItem.order_id, Order.merchant_id == merchant_id))
            .where(
                Refund.merchant_id == merchant_id,
                Refund.business_date >= start,
                Refund.business_date <= end,
                # 只统计真正完成的退款：PENDING/REJECTED 的申请不算「退款」，
                # 否则临时分组指标会把从未退过的钱算进退款金额和笔数。
                Refund.refund_status == "REFUNDED",
            )
        )
        includes_product = plan.group_by == "spu_id" or plan.filter_column == "spu_id"
        if includes_product:
            statement = statement.join(
                Product,
                and_(Product.id == OrderItem.product_id, Product.merchant_id == merchant_id),
            )
        statement = self._apply_generated_filter(statement, plan)
        group_columns, dimensions = self._generated_dimensions(plan)
        if group_columns:
            statement = (
                statement.with_only_columns(*dimensions, *metrics)
                .group_by(*group_columns)
                .order_by(refund_count.desc(), refund_amount.desc())
            )
        source_tables: tuple[str, ...] = ("refunds", "order_items", "orders")
        if includes_product:
            source_tables = (*source_tables, "products")
        return await self._fetch_with_total(
            statement,
            limit=limit if group_columns else None,
            known_total=None if group_columns else 1,
            columns=(
                *self._generated_result_columns(plan),
                *self._refund_generated_metric_columns(),
            ),
            source_tables=source_tables,
        )

    @staticmethod
    def _generated_dimensions(
        plan: GeneratedMetricPlan,
    ) -> tuple[tuple[ColumnElement[Any], ...], tuple[ColumnElement[Any], ...]]:
        if plan.group_by == "spu_id":
            spu_id = func.coalesce(Product.spu_id, Product.product_code).label("spu_id")
            return (spu_id,), (spu_id, func.max(Product.title).label("spu_name"))
        if plan.group_by == "address_city_name":
            city = func.coalesce(Order.address_city_name, "未知城市").label("address_city_name")
            return (city,), (city,)
        return (), ()

    @staticmethod
    def _generated_result_columns(plan: GeneratedMetricPlan) -> tuple[ResultColumn, ...]:
        if plan.group_by == "spu_id":
            return (
                ResultColumn("spu_id", "SPU ID", "DIMENSION"),
                ResultColumn("spu_name", "SPU 名称", "DIMENSION"),
            )
        if plan.group_by == "address_city_name":
            return (ResultColumn("address_city_name", "收货城市", "DIMENSION"),)
        return ()

    @staticmethod
    def _trade_generated_metric_columns() -> tuple[ResultColumn, ...]:
        return (
            ResultColumn("order_count", "成交订单数", "METRIC"),
            ResultColumn("order_user_count", "成交用户数", "METRIC"),
            ResultColumn("quantity", "成交件数", "METRIC"),
            ResultColumn("paid_amount", "成交金额", "METRIC"),
        )

    @staticmethod
    def _refund_generated_metric_columns() -> tuple[ResultColumn, ...]:
        return (
            ResultColumn("refund_count", "退款笔数", "METRIC"),
            ResultColumn("refund_user_count", "退款用户数", "METRIC"),
            ResultColumn("refund_amount", "退款金额", "METRIC"),
        )

    @staticmethod
    def _apply_generated_filter(statement: Select[Any], plan: GeneratedMetricPlan) -> Select[Any]:
        if plan.filter_column == "spu_id":
            assert plan.filter_value is not None
            return statement.where(
                func.coalesce(Product.spu_id, Product.product_code) == plan.filter_value
            )
        if plan.filter_column == "address_city_name":
            assert plan.filter_value is not None
            return statement.where(Order.address_city_name == plan.filter_value)
        return statement

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

        时间窗按 `spec.date_filtered` 决定加不加：事件表的 `business_date` 是
        事件发生日，维度表（商品）的是上架日，对后者套用查询区间会把绝大多数
        行静默过滤掉。该判断属于表本身的时间语义，声明在
        `app.analytics.contract.DetailSpec` 上，这里只负责尊重它。
        """

        table = _TABLES[spec.table]
        columns = [getattr(table, name) for name, _ in spec.columns]
        conditions = [table.merchant_id == merchant_id]
        if spec.date_filtered:
            conditions.extend(
                (table.business_date >= start, table.business_date <= end),
            )
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

    async def resolve_cross_business_order(
        self, *, merchant_id: UUID, sub_order_no: str
    ) -> UUID | None:
        """Only resolve an order within the verified merchant scope."""

        return cast(
            "UUID | None",
            await self._session.scalar(
                select(Order.id).where(
                    Order.merchant_id == merchant_id,
                    Order.order_no == sub_order_no,
                )
            ),
        )

    async def cross_business_detail(
        self,
        *,
        merchant_id: UUID,
        order_id: UUID,
        plan: CrossBusinessPlan,
        limit: int | None,
    ) -> DetailResult:
        """Execute a fixed, merchant-scoped order relation plan."""

        order_columns: list[ColumnElement[Any]] = [
            Order.order_no.label("order_no"),
            Order.order_status.label("order_status"),
            Order.paid_amount.label("paid_amount"),
        ]
        order_result_columns: tuple[ResultColumn, ...] = (
            ResultColumn("order_no", "订单号", "DIMENSION"),
            ResultColumn("order_status", "订单状态", "DIMENSION"),
            ResultColumn("paid_amount", "实付金额", "METRIC"),
        )
        statement: Select[Any] = (
            select(*order_columns)
            .select_from(Order)
            .join(
                OrderItem,
                and_(
                    OrderItem.order_id == Order.id,
                    OrderItem.merchant_id == merchant_id,
                ),
            )
            .where(
                Order.merchant_id == merchant_id,
                Order.id == order_id,
            )
        )

        if plan.plan_type is CrossBusinessPlanType.ORDER_TO_REFUND:
            statement = statement.outerjoin(
                Refund,
                and_(
                    Refund.order_item_id == OrderItem.id,
                    Refund.merchant_id == merchant_id,
                ),
            ).add_columns(
                Refund.refund_amount.label("refund_amount"),
                Refund.refund_reason.label("refund_reason"),
                Refund.refund_status.label("refund_status"),
                Refund.refunded_at.label("refunded_at"),
            )
            columns = (
                *order_result_columns,
                ResultColumn("refund_amount", "退款金额", "METRIC"),
                ResultColumn("refund_reason", "退款原因", "DIMENSION"),
                ResultColumn("refund_status", "退款状态", "DIMENSION"),
                ResultColumn("refunded_at", "退款时间", "DIMENSION"),
            )
            source_tables: tuple[str, ...] = ("orders", "order_items", "refunds")
        else:
            statement = statement.join(
                Product,
                and_(
                    Product.id == OrderItem.product_id,
                    Product.merchant_id == merchant_id,
                ),
            ).add_columns(
                Product.product_code.label("product_code"),
                Product.title.label("product_title"),
                Product.category.label("product_category"),
                OrderItem.quantity.label("quantity"),
                OrderItem.item_amount.label("item_amount"),
            )
            product_columns = (
                ResultColumn("product_code", "商品编码", "DIMENSION"),
                ResultColumn("product_title", "商品名称", "DIMENSION"),
                ResultColumn("product_category", "商品类目", "DIMENSION"),
                ResultColumn("quantity", "购买数量", "METRIC"),
                ResultColumn("item_amount", "商品金额", "METRIC"),
            )
            if plan.plan_type is CrossBusinessPlanType.ORDER_TO_GOODS:
                columns = (*order_result_columns, *product_columns)
                source_tables = ("orders", "order_items", "products")
            else:
                statement = statement.outerjoin(
                    Refund,
                    and_(
                        Refund.order_item_id == OrderItem.id,
                        Refund.merchant_id == merchant_id,
                    ),
                ).add_columns(
                    Refund.refund_amount.label("refund_amount"),
                    Refund.refund_reason.label("refund_reason"),
                    Refund.refund_status.label("refund_status"),
                    Refund.refunded_at.label("refunded_at"),
                )
                columns = (
                    *order_result_columns,
                    *product_columns,
                    ResultColumn("refund_amount", "退款金额", "METRIC"),
                    ResultColumn("refund_reason", "退款原因", "DIMENSION"),
                    ResultColumn("refund_status", "退款状态", "DIMENSION"),
                    ResultColumn("refunded_at", "退款时间", "DIMENSION"),
                )
                source_tables = ("orders", "order_items", "products", "refunds")

        statement = statement.order_by(OrderItem.id)
        return await self._fetch_with_total(
            statement,
            limit=limit,
            columns=columns,
            source_tables=source_tables,
        )

    async def export_cross_business(
        self, *, merchant_id: UUID, plan: CrossBusinessPlan
    ) -> DetailResult:
        order_id = await self.resolve_cross_business_order(
            merchant_id=merchant_id,
            sub_order_no=plan.sub_order_no,
        )
        if order_id is None:
            return DetailResult((), [], 0, False, ())
        return await self.cross_business_detail(
            merchant_id=merchant_id,
            order_id=order_id,
            plan=plan,
            limit=None,
        )

    async def export_detail(
        self,
        *,
        merchant_id: UUID,
        spec: DetailSpec,
        filters: Mapping[str, str],
        start: date,
        end: date,
    ) -> DetailResult:
        """用已登记的明细规格导出完整结果，绝不接受表名或列名字符串输入。"""

        table = _TABLES[spec.table]
        columns = [getattr(table, name) for name, _ in spec.columns]
        conditions = [table.merchant_id == merchant_id]
        if spec.date_filtered:
            conditions.extend((table.business_date >= start, table.business_date <= end))
        for code, value in filters.items():
            dimension = dimension_spec(code)
            if dimension.table == spec.table:
                conditions.append(getattr(table, dimension.column) == value)
        result = await self._session.execute(
            select(*columns).where(*conditions).order_by(table.business_date.desc(), table.id)
        )
        rows = [dict(row) for row in result.mappings()]
        return DetailResult(
            columns=tuple(ResultColumn(name, label, "DIMENSION") for name, label in spec.columns),
            rows=rows,
            total_rows=len(rows),
            truncated=False,
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
