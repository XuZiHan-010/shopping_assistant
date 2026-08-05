"""受控查询服务的路由、截断与拒绝。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.models.analytics import Order
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
