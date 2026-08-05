"""受控查询服务的路由、截断与拒绝。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.models.analytics import Order, OrderItem, Product, ReturnRecord, SupportTicket
from app.repositories.analytics import AnalyticsRepository
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services import safe_query
from app.services.safe_query import SafeQueryService, UnsupportedQueryError

NOW = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
DAY = date(2026, 8, 3)


def _service(session: AsyncSession) -> SafeQueryService:
    return SafeQueryService(AnalyticsRepository(session), business_timezone="Asia/Shanghai")


def _intent(**overrides: object) -> QueryIntent:
    base: dict[str, object] = {
        "answer_mode": AnswerMode.METRIC,
        "category": QuestionCategory.TRADE,
        "metric": "gmv",
        "dimensions": [],
        "filters": {},
        "date_range": DateRange(start=DAY, end=DAY),
    }
    base.update(overrides)
    return QueryIntent.model_validate(base)


async def _order(session: AsyncSession, merchant_id: UUID) -> None:
    session.add(
        Order(
            merchant_id=merchant_id,
            business_date=DAY,
            order_no=f"NO-{uuid4().hex[:8]}",
            buyer_key="buyer-1",
            order_status="COMPLETED",
            total_amount=Decimal("88.00"),
            paid_amount=Decimal("88.00"),
            placed_at=NOW,
            paid_at=NOW,
        )
    )
    await session.flush()


async def _return_record(
    session: AsyncSession, merchant_id: UUID, *, reason: str, quantity: int = 1
) -> None:
    """退货明细的最小依赖链：product -> order -> order_item -> return。

    REFUND 类别的路由缺口修复之后，这条链路第一次能通过 `SafeQueryService`
    端到端验证——此前只能在 `AnalyticsRepository` 这一层直接测（见
    `tests/integration/repositories/test_analytics_detail.py`），因为
    `DETAIL_BY_CATEGORY` 把 REFUND 写死到了 `refunds`。
    """

    product = Product(
        merchant_id=merchant_id,
        business_date=DAY,
        product_code=f"SKU-{uuid4().hex[:8]}",
        title="演示商品",
        category="女装",
        price=Decimal("100.00"),
        status="ONLINE",
        listed_at=NOW,
    )
    session.add(product)
    await session.flush()

    order = Order(
        merchant_id=merchant_id,
        business_date=DAY,
        order_no=f"NO-{uuid4().hex[:8]}",
        buyer_key="buyer",
        order_status="COMPLETED",
        total_amount=Decimal("100.00"),
        paid_amount=Decimal("100.00"),
        placed_at=NOW,
        paid_at=NOW,
    )
    session.add(order)
    await session.flush()

    item = OrderItem(
        merchant_id=merchant_id,
        business_date=DAY,
        order_id=order.id,
        product_id=product.id,
        quantity=quantity,
        item_amount=Decimal("100.00"),
    )
    session.add(item)
    await session.flush()

    session.add(
        ReturnRecord(
            merchant_id=merchant_id,
            business_date=DAY,
            order_item_id=item.id,
            return_quantity=quantity,
            return_reason=reason,
            return_status="COMPLETED",
            logistics_status="DELIVERED",
            returned_at=NOW,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_metric_intent_returns_rows_and_a_plan_summary(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _order(db_session, merchant_one_id)

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id), _intent(), now=NOW
    )

    assert result.rows == [{"gmv": Decimal("88.00")}]
    assert result.source_tables == ("orders",)
    assert result.plan_steps, "查询计划摘要不能为空"


@pytest.mark.asyncio
async def test_detail_intent_routes_by_category_and_carries_export_spec(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _order(db_session, merchant_one_id)

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(answer_mode=AnswerMode.DETAIL, metric=None),
        now=NOW,
    )

    assert result.export_spec is not None
    assert result.export_spec.table == "orders"
    assert result.total_rows == 1


@pytest.mark.asyncio
async def test_refund_category_detail_reads_the_refunds_table(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """无维度/筛选、无关键词时的兜底行为：REFUND 类别维持查 refunds 不变。"""

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            answer_mode=AnswerMode.DETAIL,
            metric=None,
            category=QuestionCategory.REFUND,
        ),
        now=NOW,
    )

    assert result.source_tables == ("refunds",)


@pytest.mark.asyncio
async def test_unknown_metric_is_refused_with_a_showable_reason(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """B3 白名单之外的指标到这里必须再被拦一次，且原因可以直接展示给用户。"""

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(metric="seller_secret_metric"),
            now=NOW,
        )

    assert "seller_secret_metric" in error.value.reason
    assert "SELECT" not in error.value.reason.upper()


@pytest.mark.asyncio
async def test_incompatible_dimension_is_refused_not_silently_dropped(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """拒绝原因要展示中文标签，不能回显原始 code——它可能就等于真实列名

    （见 `app.analytics.contract.DIMENSION_SPECS`，`refund_reason` 的
    `code` 和 `column` 是同一个字符串）。
    """

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(dimensions=["refund_reason"]),
            now=NOW,
        )

    assert "退款原因" in error.value.reason
    assert "refund_reason" not in error.value.reason


@pytest.mark.asyncio
async def test_missing_date_range_falls_back_to_the_default_window(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _order(db_session, merchant_one_id)

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id), _intent(date_range=None), now=NOW
    )

    assert any("默认" in note for note in result.notes)
    assert result.rows == [{"gmv": Decimal("88.00")}]


@pytest.mark.asyncio
async def test_non_additive_metric_is_flagged_for_the_answer_layer(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """B5 拿到这个标记才知道不能把每天的退货率加起来。"""

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(metric="return_rate", dimensions=["date"]),
        now=NOW,
    )

    assert result.non_additive is True


@pytest.mark.asyncio
async def test_sort_only_accepts_contract_keys(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """排序键会进 ORDER BY 的标识符位置，和指标、维度是同一类风险。

    `sort` 不像 metric/dimensions/filters 那样受 B3 白名单校验，拒绝原因
    绝不能把这个恶意载荷原样回显——那样"可安全展示"的错误信息本身就带着
    SQL 关键字和真实表名。
    """

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(dimensions=["date"], sort="gmv; DROP TABLE orders"),
            now=NOW,
        )

    assert "DROP" not in error.value.reason.upper()
    assert "orders" not in error.value.reason


@pytest.mark.asyncio
async def test_sort_by_metric_desc_puts_the_largest_first(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    session_orders = (("2026-08-01", "10.00"), ("2026-08-02", "90.00"))
    for day, amount in session_orders:
        db_session.add(
            Order(
                merchant_id=merchant_one_id,
                business_date=date.fromisoformat(day),
                order_no=f"NO-{uuid4().hex[:8]}",
                buyer_key="buyer",
                order_status="COMPLETED",
                total_amount=Decimal(amount),
                paid_amount=Decimal(amount),
                placed_at=NOW,
                paid_at=NOW,
            )
        )
    await db_session.flush()

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            dimensions=["date"],
            sort="-gmv",
            date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        ),
        now=NOW,
    )

    assert next(row["gmv"] for row in result.rows) == Decimal("90.00")


@pytest.mark.asyncio
async def test_fully_future_date_range_is_refused_not_silently_truncated(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """Task 4 修复轮之后 resolve_range 对完全落在未来的区间抛 FutureRangeError；

    服务层必须接住它转成 UnsupportedQueryError，不能让它冒泡成 500，也不能
    让用户以为「今天」的数据是对未来区间的正常回答。
    """

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(date_range=DateRange(start=date(2026, 8, 10), end=date(2026, 8, 12))),
            now=NOW,
        )

    assert "未来" in error.value.reason
    assert "SELECT" not in error.value.reason.upper()


@pytest.mark.asyncio
async def test_detail_filter_on_unknown_field_is_refused(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """筛选字段压根不在契约注册表里——必须拒绝，不能被仓储层悄悄忽略。"""

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(
                answer_mode=AnswerMode.DETAIL,
                metric=None,
                filters={"seller_secret_field": "x"},
            ),
            now=NOW,
        )

    assert "SELECT" not in error.value.reason.upper()


@pytest.mark.asyncio
async def test_detail_filter_from_another_table_is_refused_not_silently_dropped(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`AnalyticsRepository.detail()` 只对落在目标表上的筛选生效，其余静默丢弃。

    订单明细加了「退货原因」筛选却拿到全量订单，用户会误以为筛过了——
    这里必须在调用仓储之前就显式拒绝，而不是让它被仓储层默默吞掉。
    """

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(
                answer_mode=AnswerMode.DETAIL,
                metric=None,
                category=QuestionCategory.TRADE,
                filters={"return_reason": "质量问题"},
            ),
            now=NOW,
        )

    assert "退货原因" in error.value.reason
    assert "SELECT" not in error.value.reason.upper()
    assert "returns" not in error.value.reason
    assert "orders" not in error.value.reason


@pytest.mark.asyncio
async def test_plan_steps_never_expose_raw_table_names(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`plan_steps` 是「只承载可安全展示描述」的字段，不能把 SQLAlchemy 的表名

    夹在给商家看的中文句子里——哪怕只是英文单词混进中文也不行。分别覆盖
    orders（gmv 直查）、order_items（退货率按区间重算）、refunds（退款金额）
    三条不同的来源路径。
    """

    await _order(db_session, merchant_one_id)
    service = _service(db_session)
    context = MerchantContext(merchant_id=merchant_one_id)

    gmv_result = await service.execute(context, _intent(), now=NOW)
    ratio_result = await service.execute(
        context, _intent(metric="return_rate", dimensions=["date"]), now=NOW
    )
    refund_result = await service.execute(context, _intent(metric="refund_amount"), now=NOW)

    for result in (gmv_result, ratio_result, refund_result):
        text = "".join(result.plan_steps)
        assert "orders" not in text
        assert "order_items" not in text
        assert "refunds" not in text


@pytest.mark.asyncio
async def test_metric_result_is_truncated_when_group_count_exceeds_the_preview_limit(
    db_session: AsyncSession, merchant_one_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预览上限是「截断但可见」，不是「悄悄按不完整数据回答却说数据完整」。

    真实阈值是 200，为了不用真的构造 201 个分组，这里把服务层的预览常量
    调小后验证探测逻辑本身：向仓储多取一行，超出阈值就裁剪并标记
    truncated——`_METRIC_PREVIEW_LIMIT` 是模块级常量，服务层没有开注入口，
    所以直接 monkeypatch 模块属性。
    """

    monkeypatch.setattr(safe_query, "_METRIC_PREVIEW_LIMIT", 2)
    for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
        db_session.add(
            Order(
                merchant_id=merchant_one_id,
                business_date=date.fromisoformat(day),
                order_no=f"NO-{uuid4().hex[:8]}",
                buyer_key="buyer",
                order_status="COMPLETED",
                total_amount=Decimal("10.00"),
                paid_amount=Decimal("10.00"),
                placed_at=NOW,
                paid_at=NOW,
            )
        )
    await db_session.flush()

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            dimensions=["date"],
            date_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        ),
        now=NOW,
    )

    assert result.truncated is True
    assert len(result.rows) == 2
    assert result.total_rows == 2


@pytest.mark.asyncio
async def test_detail_without_a_mapped_table_shows_the_chinese_category_name(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """没有明细表的分类要拒绝，拒绝原因用中文业务名而不是英文枚举码。"""

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(
                answer_mode=AnswerMode.DETAIL,
                metric=None,
                category=QuestionCategory.SCM,
            ),
            now=NOW,
        )

    assert "供应链" in error.value.reason
    assert "SCM" not in error.value.reason


@pytest.mark.asyncio
async def test_refund_category_with_return_filter_routes_to_returns(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """维度/筛选字段是最强信号：出现 `return_reason` 说明用户要的是退货明细，

    不是退款明细——计划稿曾经把 REFUND 写死到 refunds，这条走不通。
    """

    await _return_record(db_session, merchant_one_id, reason="质量问题")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            answer_mode=AnswerMode.DETAIL,
            metric=None,
            category=QuestionCategory.REFUND,
            filters={"return_reason": "质量问题"},
        ),
        now=NOW,
    )

    assert result.source_tables == ("returns",)
    assert result.total_rows == 1
    assert result.rows[0]["return_quantity"] == 1


@pytest.mark.asyncio
async def test_refund_category_with_return_keyword_routes_to_returns(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """没有维度/筛选信号时退到关键词：分类阶段识别出「退货」就该查退货明细。"""

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(answer_mode=AnswerMode.DETAIL, metric=None, category=QuestionCategory.REFUND),
        now=NOW,
        keywords=("导出最近7天退货明细",),
    )

    assert result.source_tables == ("returns",)


@pytest.mark.asyncio
async def test_refund_category_with_refund_keyword_routes_to_refunds(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """关键词命中「退款」时维持查退款明细，不能被「退货」的字面相似性带偏。"""

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(answer_mode=AnswerMode.DETAIL, metric=None, category=QuestionCategory.REFUND),
        now=NOW,
        keywords=("查询退款明细",),
    )

    assert result.source_tables == ("refunds",)


@pytest.mark.asyncio
async def test_goods_detail_returns_products_listed_outside_the_query_window(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """§B4 把商品明细列为五类明细之一，但共享的时间窗规则让它实际不可用。

    `products.business_date` 是上架日：默认窗口只有 7 天，而演示数据把商品
    铺在 180 天里，商家问「看看我的商品明细」只会拿到窗口内恰好上架的那一两个。
    这里用一个半年前上架的商品钉住「不按业务日过滤」，并要求查询计划如实说明。
    """

    db_session.add(
        Product(
            merchant_id=merchant_one_id,
            business_date=DAY - timedelta(days=170),
            product_code="SKU-OLD",
            title="半年前上架的商品",
            category="女装",
            price=Decimal("100.00"),
            status="ONLINE",
            listed_at=NOW,
        )
    )
    await db_session.flush()

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            answer_mode=AnswerMode.DETAIL,
            metric=None,
            category=QuestionCategory.GOODS,
            date_range=None,
        ),
        now=NOW,
    )

    assert result.source_tables == ("products",)
    assert [row["product_code"] for row in result.rows] == ["SKU-OLD"]
    plan = "".join(result.plan_steps)
    assert "不限时间范围" in plan
    assert "至" not in plan, "没按日期过滤就不能给出一个假的时间范围承诺"
    assert any("不按日期筛选" in note for note in result.notes)


@pytest.mark.asyncio
async def test_support_ticket_metric_and_detail_run_against_the_real_table(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`support_ticket_count` 与工单明细此前从未连库跑过。

    `_metric_expression` 和 `detail()` 都按契约里登记的名字解析列，写错只会在
    真的查那张表时才炸——这条把「工单能聚合、也能出明细」一次钉住。
    """

    db_session.add(
        SupportTicket(
            merchant_id=merchant_one_id,
            business_date=DAY,
            ticket_no="TK-0001",
            order_id=None,
            ticket_status="OPEN",
            ticket_reason="物流查询",
            opened_at=NOW,
        )
    )
    await db_session.flush()
    service = _service(db_session)
    context = MerchantContext(merchant_id=merchant_one_id)

    metric_result = await service.execute(
        context,
        _intent(metric="support_ticket_count", category=QuestionCategory.CS_TICKET),
        now=NOW,
    )
    detail_result = await service.execute(
        context,
        _intent(answer_mode=AnswerMode.DETAIL, metric=None, category=QuestionCategory.CS_TICKET),
        now=NOW,
    )

    assert metric_result.rows == [{"support_ticket_count": 1}]
    assert metric_result.source_tables == ("support_tickets",)
    assert [row["ticket_no"] for row in detail_result.rows] == ["TK-0001"]


@pytest.mark.asyncio
async def test_support_ticket_metric_splits_by_ticket_status(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """按工单状态拆分是这张表唯一的自有维度，同样从未跑过。"""

    for index, status in enumerate(("OPEN", "OPEN", "CLOSED")):
        db_session.add(
            SupportTicket(
                merchant_id=merchant_one_id,
                business_date=DAY,
                ticket_no=f"TK-{index:04d}",
                order_id=None,
                ticket_status=status,
                ticket_reason="物流查询",
                opened_at=NOW,
            )
        )
    await db_session.flush()

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            metric="support_ticket_count",
            category=QuestionCategory.CS_TICKET,
            dimensions=["ticket_status"],
        ),
        now=NOW,
    )

    assert {row["ticket_status"]: row["support_ticket_count"] for row in result.rows} == {
        "OPEN": 2,
        "CLOSED": 1,
    }


@pytest.mark.asyncio
async def test_refund_category_return_routing_never_leaks_another_merchant(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    """§B4 验收「退货明细可查询、可导出，跨商家退货记录不可见」的端到端钉子。

    路由缺口修复前这条走不通——REFUND 永远查 refunds，returns 表压根到不了，
    `SafeQueryService` 这一层就没法验证商家隔离。两个商家同一天都有退货
    原因相同的记录，但件数不同：如果隔离失效，返回行会同时出现 3 和 9。
    """

    await _return_record(db_session, merchant_one_id, reason="质量问题", quantity=3)
    await _return_record(db_session, merchant_two_id, reason="质量问题", quantity=9)

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(
            answer_mode=AnswerMode.DETAIL,
            metric=None,
            category=QuestionCategory.REFUND,
            filters={"return_reason": "质量问题"},
        ),
        now=NOW,
    )

    assert result.source_tables == ("returns",)
    assert [row["return_quantity"] for row in result.rows] == [3]
