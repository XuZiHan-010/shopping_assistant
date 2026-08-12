# 后端 B4「安全经营数据查询」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 B3 已经理解好的 `QueryIntent` 真正查到数——建六张演示经营表和 180 天数据，用受控 SQLAlchemy 表达式（绝不拼接用户输入）执行指标聚合与明细查询，强制商家隔离、日期上限和行数上限，并把结果接回问答图，让 METRIC / DETAIL / IDENTITY 回答从 `FALLBACK` 降级变成真实数据。

**Architecture:** 用户输入永远不进入 SQL 的标识符位置。指标和维度各有一张**代码内的契约注册表**（`metric_code` → 表与聚合表达式、`dimension` → 列与中文标签），查询层只接受注册表里的键；值参数一律绑定。Repository 只出受控查询，Service 负责路由（`answer_mode + category + metric`）、日期解析、截断和查询计划摘要。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2.0（async，Core 表达式）、Alembic、Pydantic v2、PostgreSQL、pytest、Ruff、mypy。

## Global Constraints

- 用户可见文案与数据标签使用中文，代码标识符使用英文。
- **商家身份只能来自 Bearer Token 解析出的 `MerchantContext`**；请求体、查询参数中的 `merchant_id` 一律忽略。每一条经营查询都必须带 `merchant_id` 过滤，没有例外。
- **LLM 不得生成或执行 SQL（R4）。** 本阶段所有 SQL 由 SQLAlchemy 表达式构造，表名和列名只能来自代码内注册表。
- **B3 的白名单不是唯一防线。** 查询层必须再校验一次——指标与维度会进入 SQL 的标识符位置，那里无法参数化绑定。
- 日期范围上限 **180 天**，明细预览上限 **200 行**，二者都是「后端截断」而非报错。
- 业务时区固定 `Asia/Shanghai`，由配置提供；时钟必须可注入，以便冻结时钟测试跨零点行为。
- 禁止 `SELECT *`；禁止把数据库异常原文返回用户。
- 金额用 `NUMERIC`，时间用 `TIMESTAMPTZ` 存 UTC，所有经营表含非空 `merchant_id` 与 `created_at`。
- Seed **不属于 Migration**；Migration 不调用网络或 LLM，可在空库重复执行。
- **本阶段不发生任何真实 LLM 调用**（R3）。测试一律用 `FakeLlmClient`。
- 项目规则禁止未经明确授权的 Git commit/push/PR（R2）。**各 Task 的「Commit」步骤需获授权后执行**；未获授权时以「全部门禁通过」替代。

**后端门禁（每个 Task 结束都要跑）：**

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

集成测试需要本地 PostgreSQL（`tests/postgres.py` 的 `DEFAULT_TEST_DATABASE_URL`，库名须以 `_test` 结尾）；未启动时相关用例自动跳过，但**本阶段的验收必须在真实库上跑过一次**。

---

## 文件结构

新建的代码按职责分三层，不按技术层切：

| 文件 | 职责 |
| --- | --- |
| `backend/app/models/analytics.py` | 六张经营表的 ORM。只描述结构，不含查询逻辑 |
| `backend/migrations/versions/20260804_0005_create_demo_analytics.py` | 建表与索引 |
| `backend/app/analytics/contract.py` | **指标与维度的 SQL 契约注册表**。`metric_code` / `dimension` 到表、列、聚合表达式的唯一映射；查询层只认这里的键 |
| `backend/app/analytics/dates.py` | 业务时区日界与日期范围解析（可注入时钟） |
| `backend/app/analytics/demo_data.py` | 180 天演示数据的**纯生成逻辑**（不碰数据库，便于单测） |
| `backend/scripts/seed_demo_analytics.py` | 把上面的数据写库的 CLI 包装 |
| `backend/app/repositories/analytics.py` | 受控聚合查询与明细查询。强制 `merchant_id`，参数绑定 |
| `backend/app/services/safe_query.py` | 路由、截断、查询计划摘要、非加和保护，产出 `QueryResult` |
| `backend/app/schemas/metric.py` | `GET /api/metrics/{code}` 的响应 Schema |
| `backend/app/api/routes/metrics.py` | 指标口径端点 |

生成逻辑与写库分开（`demo_data.py` / `seed_demo_analytics.py`）是有意的：Seed 的正确性（是否包含「只退款不退货」样本、日期是否覆盖 180 天）必须能在不起数据库的单测里验证。

---

## 指标口径契约（本阶段定稿）

以下九条是 B3 白名单里的全部指标。**口径在这里定死，Task 3 的注册表与 `app/metrics/seed.py` 的 `business_definition` 必须与本表逐字一致**，否则用户在口径面板看到的说明与实际算法不符。

| `metric_code` | 中文名 | 单位 | 口径 | 可加和 |
| --- | --- | --- | --- | --- |
| `gmv` | 成交 GMV | 元 | `SUM(orders.paid_amount)`，限 `order_status IN ('PAID','SHIPPED','COMPLETED')` | 是 |
| `order_count` | 订单量 | 单 | `COUNT(orders.id)`，不限状态 | 是 |
| `paying_user_count` | 付款用户数 | 人 | `COUNT(DISTINCT orders.buyer_key)`，限 `paid_at IS NOT NULL` | **否**（去重，跨区间不可相加） |
| `successful_order_count` | 成功订单量 | 单 | `COUNT(orders.id)`，限 `order_status = 'COMPLETED'` | 是 |
| `refund_count` | 退款量 | 单 | `COUNT(refunds.id)`，限 `refund_status IN ('APPROVED','REFUNDED')` | 是 |
| `refund_amount` | 退款金额 | 元 | `SUM(refunds.refund_amount)`，限 `refund_status = 'REFUNDED'` | 是 |
| `return_count` | 退货量 | 件 | `SUM(returns.return_quantity)` | 是 |
| `return_rate` | 退货率 | % | 退货件数 ÷ 同期订单项件数，见下 | **否**（比例） |
| `support_ticket_count` | 客服工单量 | 单 | `COUNT(support_tickets.id)` | 是 |

**`return_rate` 的归属与防重复计数**。退货件数按**订单项所属的下单日**归属（回答「这批订单里有多少被退了」），而不是按退货发生日——后者会让分母（同期订单项）对不上。为避免一个订单项有多条退货记录时把分母重复计入，先把 `returns` 按 `order_item_id` 聚合成子查询，再 LEFT JOIN 到 `order_items`：

```sql
WITH returns_agg AS (
  SELECT order_item_id, SUM(return_quantity) AS returned_quantity
  FROM returns WHERE merchant_id = :merchant_id GROUP BY order_item_id
)
SELECT SUM(COALESCE(ra.returned_quantity, 0))::numeric
       / NULLIF(SUM(oi.quantity), 0) AS value
FROM order_items oi LEFT JOIN returns_agg ra ON ra.order_item_id = oi.id
WHERE oi.merchant_id = :merchant_id AND oi.business_date BETWEEN :start AND :end
```

**`refund_count` / `refund_amount` 取自 `refunds`，`return_count` 取自 `returns`，两者不得互相替代**——退款是资金动作，退货是货品动作，可以单独发生。

## 维度契约

| `dimension` | 中文标签 | 落到的列 |
| --- | --- | --- |
| `date` | 日期 | 该指标主表的 `business_date` |
| `product` | 商品 | `products.title`（经 `order_items.product_id` 关联） |
| `category` | 类目 | `products.category` |
| `order_status` | 订单状态 | `orders.order_status` |
| `refund_reason` | 退款原因 | `refunds.refund_reason` |
| `return_reason` | 退货原因 | `returns.return_reason` |
| `return_status` | 退货状态 | `returns.return_status` |
| `ticket_status` | 工单状态 | `support_tickets.ticket_status` |

维度只有在与指标主表兼容时才可用（例如 `refund_reason` 不能用于 `gmv`）。不兼容组合由 Task 7 显式拒绝并给出可展示原因，不是静默忽略。

---

### Task 1: 经营表 ORM 与迁移

**Files:**
- Create: `backend/app/models/analytics.py`
- Create: `backend/migrations/versions/20260804_0005_create_demo_analytics.py`
- Modify: `backend/tests/postgres.py`（`TRUNCATE_ALL_TABLES` 追加六张新表）
- Test: `backend/tests/unit/models/test_analytics_metadata.py`

**Interfaces:**
- Produces: `Product`、`Order`、`OrderItem`、`Refund`、`ReturnRecord`、`SupportTicket` 六个 ORM 类，表名分别为 `products`、`orders`、`order_items`、`refunds`、`returns`、`support_tickets`。
- Produces: 每张表都有 `merchant_id: Mapped[UUID]`（非空）与 `business_date: Mapped[date]`（非空）。

`business_date` 是**写入时按 `Asia/Shanghai` 换算出的业务日**，也是查询唯一会过滤和分组的日期列。保留它而不是每次查询时做 `AT TIME ZONE` 转换，是因为计划 §7.3 要求 `merchant_id + business_date` 联合索引——表达式索引在这里没有收益，只会让每条查询都要复述时区。写入方只有 Seed 一处，不存在多处写入导致漂移的风险。

- [ ] **Step 1: 写失败的元数据测试**

`backend/tests/unit/models/test_analytics_metadata.py`：

```python
"""经营表的结构约束。

这些断言看着琐碎，但每一条都对应一个会泄漏或算错的场景：缺 merchant_id 就是
跨商家泄漏，缺 business_date 索引就是全表扫，金额用 float 就是对不上账。
"""

from __future__ import annotations

import pytest
from sqlalchemy import Numeric

from app.models.analytics import (
    Order,
    OrderItem,
    Product,
    Refund,
    ReturnRecord,
    SupportTicket,
)

ANALYTICS_MODELS = [Product, Order, OrderItem, Refund, ReturnRecord, SupportTicket]


@pytest.mark.parametrize("model", ANALYTICS_MODELS, ids=lambda m: m.__tablename__)
def test_every_analytics_table_carries_a_non_null_merchant_id(model: type) -> None:
    column = model.__table__.c["merchant_id"]

    assert column.nullable is False


@pytest.mark.parametrize("model", ANALYTICS_MODELS, ids=lambda m: m.__tablename__)
def test_every_analytics_table_carries_a_non_null_business_date(model: type) -> None:
    column = model.__table__.c["business_date"]

    assert column.nullable is False


@pytest.mark.parametrize("model", ANALYTICS_MODELS, ids=lambda m: m.__tablename__)
def test_every_analytics_table_indexes_merchant_and_business_date(model: type) -> None:
    expected = {"merchant_id", "business_date"}
    index_columns = [{column.name for column in index.columns} for index in model.__table__.indexes]

    assert any(expected <= columns for columns in index_columns), model.__tablename__


@pytest.mark.parametrize(
    ("model", "column_name"),
    [
        (Order, "paid_amount"),
        (Order, "total_amount"),
        (OrderItem, "item_amount"),
        (Product, "price"),
        (Refund, "refund_amount"),
    ],
)
def test_money_columns_use_numeric_not_float(model: type, column_name: str) -> None:
    assert isinstance(model.__table__.c[column_name].type, Numeric)


def test_refunds_and_returns_are_separate_tables_linked_to_order_items() -> None:
    """退款是资金动作、退货是货品动作，可以单独发生，合表会让两类指标互相污染。"""

    assert Refund.__tablename__ == "refunds"
    assert ReturnRecord.__tablename__ == "returns"
    for model in (Refund, ReturnRecord):
        foreign_keys = model.__table__.c["order_item_id"].foreign_keys
        assert {key.column.table.name for key in foreign_keys} == {"order_items"}


def test_returns_track_quantity_and_logistics_separately_from_refund_amount() -> None:
    """「最近 30 天退货量趋势」要能返回件数，不能退化成退款金额。"""

    assert "return_quantity" in ReturnRecord.__table__.c
    assert "logistics_status" in ReturnRecord.__table__.c
    assert "refund_amount" not in ReturnRecord.__table__.c
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/unit/models/test_analytics_metadata.py -q`

Expected: FAIL，`ModuleNotFoundError: No module named 'app.models.analytics'`。

- [ ] **Step 3: 写 ORM**

`backend/app/models/analytics.py`：

```python
"""P0 演示经营数据 ORM。

`business_date` 是写入时按 Asia/Shanghai 换算的业务日，也是查询唯一会过滤和
分组的日期列；`*_at` 保留 UTC 时刻用于展示和排查。两者只由 Seed 一处写入。

退款（资金动作）与退货（货品动作）分表：二者可以单独发生，也可以同时发生，
合表会让「退货量」和「退款金额」互相污染。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin

_MONEY = Numeric(14, 2)


class _MerchantScopedMixin:
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)


class Product(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ONLINE', 'OFFLINE', 'AUDITING', 'REJECTED')",
            name="ck_products_status",
        ),
        UniqueConstraint("merchant_id", "product_code", name="uq_products_merchant_code"),
        Index("ix_products_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_products_merchant_category", "merchant_id", "category"),
    )

    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Order(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "order_status IN ('CREATED', 'PAID', 'SHIPPED', 'COMPLETED', 'CANCELLED', 'CLOSED')",
            name="ck_orders_status",
        ),
        UniqueConstraint("merchant_id", "order_no", name="uq_orders_merchant_no"),
        Index("ix_orders_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_orders_merchant_status", "merchant_id", "order_status"),
    )

    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 去重买家用的稳定标识。演示数据不含真实身份信息，只是一个稳定的假名。
    buyer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    order_status: Mapped[str] = mapped_column(String(16), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderItem(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index("ix_order_items_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_order_items_order", "order_id"),
    )

    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    item_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)


class Refund(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(
            "refund_status IN ('PENDING', 'APPROVED', 'REJECTED', 'REFUNDED')",
            name="ck_refunds_status",
        ),
        Index("ix_refunds_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_refunds_order_item", "order_item_id"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    refund_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    refund_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    refund_status: Mapped[str] = mapped_column(String(16), nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReturnRecord(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "returns"
    __table_args__ = (
        CheckConstraint(
            "return_status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'RECEIVED', 'COMPLETED')",
            name="ck_returns_status",
        ),
        CheckConstraint(
            "logistics_status IN ('PENDING', 'SHIPPED', 'DELIVERED', 'LOST')",
            name="ck_returns_logistics_status",
        ),
        Index("ix_returns_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_returns_order_item", "order_item_id"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    return_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    return_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    return_status: Mapped[str] = mapped_column(String(16), nullable=False)
    logistics_status: Mapped[str] = mapped_column(String(16), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportTicket(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint(
            "ticket_status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED')",
            name="ck_support_tickets_status",
        ),
        UniqueConstraint("merchant_id", "ticket_no", name="uq_support_tickets_merchant_no"),
        Index("ix_support_tickets_merchant_business_date", "merchant_id", "business_date"),
    )

    ticket_no: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    ticket_status: Mapped[str] = mapped_column(String(16), nullable=False)
    ticket_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 4: 让模型进入 Alembic 的 metadata**

确认 `backend/app/db/base.py`（或 `migrations/env.py` 引用的聚合模块）import 了新模块。若该文件是逐个 import 模型模块的形式，追加：

```python
from app.models import analytics  # noqa: F401
```

- [ ] **Step 5: 生成并编辑迁移**

Run: `cd backend && uv run alembic revision --autogenerate -m "create demo analytics"`

把生成文件重命名为 `20260804_0005_create_demo_analytics.py`，核对 `revision = "20260804_0005"`、`down_revision = "20260804_0004"`，并检查自动生成的建表语句包含全部 CHECK 约束与索引（autogenerate 偶尔漏 CheckConstraint，缺什么补什么）。`downgrade()` 按依赖倒序 drop：`support_tickets` → `returns` → `refunds` → `order_items` → `orders` → `products`。

- [ ] **Step 6: 让集成测试能清库**

`backend/tests/postgres.py` 的 `TRUNCATE_ALL_TABLES` 追加新表（放在最前面，CASCADE 会处理依赖）：

```python
TRUNCATE_ALL_TABLES = (
    "TRUNCATE TABLE support_tickets, returns, refunds, order_items, orders, products, "
    "audit_logs, feedback, answers, messages, "
    "conversations, llm_usage, metric_definitions, "
    "knowledge_documents, merchants CASCADE"
)
```

- [ ] **Step 7: 在真实库上验证迁移**

Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`

Expected: 三次都成功，无残留对象。

- [ ] **Step 8: 跑测试与门禁**

Run: `cd backend && uv run pytest tests/unit/models/ -q`，Expected: PASS。

再跑四条门禁。

---

### Task 2: 180 天演示数据

**Files:**
- Create: `backend/app/analytics/__init__.py`（空）
- Create: `backend/app/analytics/demo_data.py`
- Create: `backend/scripts/seed_demo_analytics.py`
- Test: `backend/tests/unit/analytics/__init__.py`（空）、`backend/tests/unit/analytics/test_demo_data.py`

**Interfaces:**
- Consumes: Task 1 的 ORM。
- Produces: `@dataclass(frozen=True) DemoDataset(products, orders, order_items, refunds, returns, tickets)`，六个字段都是 `list[dict[str, object]]`（可直接喂给 SQLAlchemy 的批量 insert）。
- Produces: `build_demo_dataset(*, merchant_id: UUID, end_date: date, days: int = 180, seed: int) -> DemoDataset`。
- Produces: CLI `uv run python scripts/seed_demo_analytics.py [--days 180]`。

- [ ] **Step 1: 写失败的生成器测试**

`backend/tests/unit/analytics/test_demo_data.py`：

```python
"""演示数据生成。

不碰数据库：Seed 的正确性（覆盖天数、退款退货的组合样本、商家隔离）必须能在
没有 PostgreSQL 的机器上验证，否则这些性质只能靠人工翻库确认。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.analytics.demo_data import build_demo_dataset

MERCHANT = UUID("00000000-0000-0000-0000-000000000001")
END = date(2026, 8, 4)


def _dataset():
    return build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=20260804)


def test_orders_cover_exactly_the_requested_window() -> None:
    dataset = _dataset()

    dates = {row["business_date"] for row in dataset.orders}

    assert min(dates) == date(2026, 2, 6)
    assert max(dates) == END
    assert len(dates) == 180


def test_generation_is_deterministic_for_the_same_seed() -> None:
    """演示数据不确定，就没法复现「昨天 GMV 是多少」这类断言。"""

    first = build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=1)
    second = build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=1)

    assert first.orders == second.orders
    assert first.returns == second.returns


def test_every_row_carries_the_requested_merchant() -> None:
    dataset = _dataset()

    for rows in (
        dataset.products,
        dataset.orders,
        dataset.order_items,
        dataset.refunds,
        dataset.returns,
        dataset.tickets,
    ):
        assert rows
        assert {row["merchant_id"] for row in rows} == {MERCHANT}


def test_dataset_contains_refund_only_and_refund_with_return_samples() -> None:
    """PRD 要求退款与退货各自成域：只有两种样本同时存在，才能验证二者不混淆。"""

    dataset = _dataset()
    refunded_items = {row["order_item_id"] for row in dataset.refunds}
    returned_items = {row["order_item_id"] for row in dataset.returns}

    assert refunded_items - returned_items, "缺少「只退款不退货」样本"
    assert refunded_items & returned_items, "缺少「退货并退款」样本"
    assert returned_items - refunded_items, "缺少「只退货不退款」样本"


def test_order_item_business_date_follows_the_order_not_the_refund() -> None:
    """退货率的分母按下单日归属；订单项的业务日跟着订单走。"""

    dataset = _dataset()
    order_dates = {row["id"]: row["business_date"] for row in dataset.orders}

    for item in dataset.order_items:
        assert item["business_date"] == order_dates[item["order_id"]]


def test_money_values_are_decimal_not_float() -> None:
    dataset = _dataset()

    assert all(isinstance(row["paid_amount"], Decimal) for row in dataset.orders)
    assert all(isinstance(row["refund_amount"], Decimal) for row in dataset.refunds)


def test_paid_orders_have_a_paid_at_and_cancelled_ones_do_not() -> None:
    dataset = _dataset()

    for order in dataset.orders:
        if order["order_status"] in {"PAID", "SHIPPED", "COMPLETED"}:
            assert order["paid_at"] is not None
        if order["order_status"] == "CANCELLED":
            assert order["paid_at"] is None
            assert order["paid_amount"] == Decimal("0.00")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/unit/analytics/ -q`

Expected: FAIL，`ModuleNotFoundError: No module named 'app.analytics'`。

- [ ] **Step 3: 实现生成器**

`backend/app/analytics/demo_data.py`：

```python
"""180 天演示经营数据的纯生成逻辑。

只产出普通字典，不碰数据库也不 import ORM——Seed 的性质要能在没有
PostgreSQL 的机器上被测试覆盖。随机数固定种子，保证同一天的演示数据可复现。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")

_CATEGORIES = ("女装", "男装", "鞋靴", "家居", "美妆")
_ORDER_STATUSES = ("CREATED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED", "CLOSED")
_REFUND_REASONS = ("商品质量问题", "尺码不合适", "发货太慢", "拍错了", "不想要了")
_RETURN_REASONS = ("商品质量问题", "尺码不合适", "与描述不符", "包装破损")
_RETURN_STATUSES = ("REQUESTED", "APPROVED", "RECEIVED", "COMPLETED", "REJECTED")
_LOGISTICS_STATUSES = ("PENDING", "SHIPPED", "DELIVERED", "LOST")
_TICKET_STATUSES = ("OPEN", "PENDING", "RESOLVED", "CLOSED")
_TICKET_REASONS = ("物流查询", "退款进度", "商品咨询", "投诉建议")


@dataclass(frozen=True)
class DemoDataset:
    products: list[dict[str, object]]
    orders: list[dict[str, object]]
    order_items: list[dict[str, object]]
    refunds: list[dict[str, object]]
    returns: list[dict[str, object]]
    tickets: list[dict[str, object]]


def _utc_moment(business_day: date, hour: int, minute: int) -> datetime:
    """把业务时区的时刻转成 UTC 存储值。"""

    local = datetime.combine(business_day, time(hour, minute), tzinfo=BUSINESS_TIMEZONE)
    return local.astimezone(ZoneInfo("UTC"))


def _money(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def build_demo_dataset(
    *,
    merchant_id: UUID,
    end_date: date,
    days: int = 180,
    seed: int,
) -> DemoDataset:
    rng = random.Random(seed)
    start_date = end_date - timedelta(days=days - 1)

    products: list[dict[str, object]] = []
    for index in range(24):
        listed_day = start_date + timedelta(days=rng.randrange(days))
        products.append(
            {
                "id": uuid4(),
                "merchant_id": merchant_id,
                "business_date": listed_day,
                "product_code": f"SKU{index:04d}",
                "title": f"演示商品 {index + 1:02d}",
                "category": _CATEGORIES[index % len(_CATEGORIES)],
                "price": _money(rng.uniform(39, 899)),
                "status": "ONLINE" if index % 8 else "AUDITING",
                "listed_at": _utc_moment(listed_day, 10, 0),
            }
        )

    orders: list[dict[str, object]] = []
    order_items: list[dict[str, object]] = []
    refunds: list[dict[str, object]] = []
    returns: list[dict[str, object]] = []
    tickets: list[dict[str, object]] = []

    for offset in range(days):
        business_day = start_date + timedelta(days=offset)
        # 周末单量略高，让「最近 7 天趋势」这类问题有可见的形状。
        daily_orders = rng.randrange(6, 14) + (3 if business_day.weekday() >= 5 else 0)

        for sequence in range(daily_orders):
            status = _ORDER_STATUSES[rng.randrange(len(_ORDER_STATUSES))]
            paid = status in {"PAID", "SHIPPED", "COMPLETED"}
            order_id = uuid4()
            item_count = rng.randrange(1, 4)
            item_rows: list[dict[str, object]] = []
            total = Decimal("0.00")

            for _ in range(item_count):
                product = products[rng.randrange(len(products))]
                quantity = rng.randrange(1, 4)
                amount = Decimal(str(product["price"])) * quantity
                total += amount
                item_rows.append(
                    {
                        "id": uuid4(),
                        "merchant_id": merchant_id,
                        # 订单项跟着订单的下单日，退货率的分母才对得上同期口径。
                        "business_date": business_day,
                        "order_id": order_id,
                        "product_id": product["id"],
                        "quantity": quantity,
                        "item_amount": amount,
                    }
                )

            orders.append(
                {
                    "id": order_id,
                    "merchant_id": merchant_id,
                    "business_date": business_day,
                    "order_no": f"NO{business_day:%Y%m%d}{sequence:03d}",
                    "buyer_key": f"buyer-{rng.randrange(1, 240):03d}",
                    "order_status": status,
                    "total_amount": total,
                    "paid_amount": total if paid else Decimal("0.00"),
                    "placed_at": _utc_moment(business_day, rng.randrange(0, 24), rng.randrange(60)),
                    "paid_at": _utc_moment(business_day, 12, 0) if paid else None,
                }
            )
            order_items.extend(item_rows)

            if not paid:
                continue

            # 三类售后样本按固定比例产出，保证「只退款」「只退货」「退货并退款」都存在。
            draw = rng.random()
            item = item_rows[0]
            refund_day = min(business_day + timedelta(days=rng.randrange(1, 6)), end_date)
            if draw < 0.08:
                refunds.append(_refund_row(merchant_id, item, refund_day, rng))
            elif draw < 0.14:
                returns.append(_return_row(merchant_id, item, refund_day, rng))
            elif draw < 0.20:
                refunds.append(_refund_row(merchant_id, item, refund_day, rng))
                returns.append(_return_row(merchant_id, item, refund_day, rng))

            if rng.random() < 0.10:
                ticket_day = min(business_day + timedelta(days=rng.randrange(0, 4)), end_date)
                tickets.append(
                    {
                        "id": uuid4(),
                        "merchant_id": merchant_id,
                        "business_date": ticket_day,
                        "ticket_no": f"TK{ticket_day:%Y%m%d}{len(tickets):04d}",
                        "order_id": order_id,
                        "ticket_status": _TICKET_STATUSES[rng.randrange(len(_TICKET_STATUSES))],
                        "ticket_reason": _TICKET_REASONS[rng.randrange(len(_TICKET_REASONS))],
                        "opened_at": _utc_moment(ticket_day, rng.randrange(9, 21), 0),
                    }
                )

    return DemoDataset(products, orders, order_items, refunds, returns, tickets)


def _refund_row(
    merchant_id: UUID,
    item: dict[str, object],
    business_day: date,
    rng: random.Random,
) -> dict[str, object]:
    status = "REFUNDED" if rng.random() < 0.8 else "PENDING"
    return {
        "id": uuid4(),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "order_item_id": item["id"],
        "refund_amount": Decimal(str(item["item_amount"])),
        "refund_reason": _REFUND_REASONS[rng.randrange(len(_REFUND_REASONS))],
        "refund_status": status,
        "refunded_at": _utc_moment(business_day, 15, 0) if status == "REFUNDED" else None,
    }


def _return_row(
    merchant_id: UUID,
    item: dict[str, object],
    business_day: date,
    rng: random.Random,
) -> dict[str, object]:
    status = _RETURN_STATUSES[rng.randrange(len(_RETURN_STATUSES))]
    return {
        "id": uuid4(),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "order_item_id": item["id"],
        "return_quantity": int(item["quantity"]),  # type: ignore[arg-type]
        "return_reason": _RETURN_REASONS[rng.randrange(len(_RETURN_REASONS))],
        "return_status": status,
        "logistics_status": _LOGISTICS_STATUSES[rng.randrange(len(_LOGISTICS_STATUSES))],
        "returned_at": _utc_moment(business_day, 16, 0) if status != "REQUESTED" else None,
    }
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && uv run pytest tests/unit/analytics/ -q`

Expected: PASS，8 个测试。若 `test_orders_cover_exactly_the_requested_window` 失败，检查是否每天都至少生成一单（`daily_orders` 下限必须 ≥ 1）。

- [ ] **Step 5: 写 Seed CLI**

`backend/scripts/seed_demo_analytics.py`：

```python
"""把 180 天演示经营数据写入数据库。

Seed 不属于 Migration（计划 §7.4）：迁移必须永远可复现，而演示数据会随
阶段调整。脚本按商家整体重写，可重复执行。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import delete

from app.analytics.demo_data import build_demo_dataset
from app.core.config import Settings
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.services.seed_service import default_merchants

_DELETE_ORDER = (SupportTicket, ReturnRecord, Refund, OrderItem, Order, Product)


async def _seed(days: int, end_date: date) -> int:
    settings = Settings()  # type: ignore[call-arg]
    database = Database(settings)
    written = 0
    async with database.session() as session:
        for index, merchant in enumerate(default_merchants()):
            for model in _DELETE_ORDER:
                await session.execute(delete(model).where(model.merchant_id == merchant.id))
            dataset = build_demo_dataset(
                merchant_id=merchant.id,
                end_date=end_date,
                days=days,
                seed=20260804 + index,
            )
            for model, rows in (
                (Product, dataset.products),
                (Order, dataset.orders),
                (OrderItem, dataset.order_items),
                (Refund, dataset.refunds),
                (ReturnRecord, dataset.returns),
                (SupportTicket, dataset.tickets),
            ):
                if rows:
                    await session.execute(model.__table__.insert(), rows)
                    written += len(rows)
        await session.commit()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="写入演示经营数据")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    total = asyncio.run(_seed(args.days, args.end_date))
    print(f"已写入 {total} 行演示经营数据")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 实跑一次并抽查**

```bash
cd backend
uv run alembic upgrade head
uv run python scripts/seed_demo_analytics.py
```

Expected: 打印行数（三个商家合计约 1.5 万行量级）。再抽查隔离与分表：

```sql
SELECT merchant_id, count(*) FROM orders GROUP BY 1;          -- 三个商家各有数据
SELECT count(*) FROM refunds r JOIN returns rt USING (order_item_id);  -- > 0，退货并退款样本
```

- [ ] **Step 7: 门禁**

---

### Task 3: 指标与维度的 SQL 契约注册表

**Files:**
- Create: `backend/app/analytics/contract.py`
- Modify: `backend/app/metrics/seed.py`（把 `sql_definition` 从占位改成真实口径）
- Create: `backend/migrations/versions/20260804_0006_metric_sql_definition.py`
- Test: `backend/tests/unit/analytics/test_contract.py`

**Interfaces:**
- Consumes: Task 1 的 ORM、B3 的 `METRIC_WHITELIST` / `DIMENSION_WHITELIST`。
- Produces: `@dataclass(frozen=True) MetricSpec(code, label, unit, table, additive, kind)`，`kind` 取 `"SIMPLE" | "RATIO"`。
- Produces: `@dataclass(frozen=True) DimensionSpec(code, label, table, column)`。
- Produces: `METRIC_SPECS: Mapping[str, MetricSpec]`、`DIMENSION_SPECS: Mapping[str, DimensionSpec]`。
- Produces: `metric_spec(code: str) -> MetricSpec`、`dimension_spec(code: str) -> DimensionSpec`，键不存在时抛 `UnknownFieldError`。
- Produces: `class UnknownFieldError(LookupError)`。
- Produces: `compatible_dimensions(metric: MetricSpec) -> frozenset[str]`。

- [ ] **Step 1: 写失败的契约测试**

`backend/tests/unit/analytics/test_contract.py`：

```python
"""指标与维度的 SQL 契约。

这张注册表是「用户输入永远不进入 SQL 标识符位置」的兑现方式：查询层只接受
这里的键，别的一律拒绝。它与 B3 白名单漂移，就等于开了一个静默失效的口子。
"""

from __future__ import annotations

import pytest

from app.analytics.contract import (
    DIMENSION_SPECS,
    METRIC_SPECS,
    UnknownFieldError,
    compatible_dimensions,
    dimension_spec,
    metric_spec,
)
from app.intent.whitelist import DIMENSION_WHITELIST, METRIC_WHITELIST


def test_metric_registry_matches_the_intent_whitelist() -> None:
    assert set(METRIC_SPECS) == set(METRIC_WHITELIST)


def test_dimension_registry_matches_the_intent_whitelist() -> None:
    assert set(DIMENSION_SPECS) == set(DIMENSION_WHITELIST)


def test_registry_matches_the_metric_seed() -> None:
    from app.metrics.seed import METRIC_SEED

    seed = {item.metric_code: item for item in METRIC_SEED}
    for code, spec in METRIC_SPECS.items():
        assert seed[code].display_name == spec.label, code
        assert seed[code].unit == spec.unit, code


@pytest.mark.parametrize("code", ["paying_user_count", "return_rate"])
def test_non_additive_metrics_are_marked(code: str) -> None:
    """去重计数和比例跨区间相加就是错的；标记丢失时 B5 会把它们求和。"""

    assert METRIC_SPECS[code].additive is False


@pytest.mark.parametrize("code", ["gmv", "order_count", "refund_amount", "return_count"])
def test_additive_metrics_are_marked(code: str) -> None:
    assert METRIC_SPECS[code].additive is True


def test_refund_and_return_metrics_read_different_tables() -> None:
    """退款是资金动作、退货是货品动作，读错表就会「退货量趋势」返回退款数据。"""

    assert METRIC_SPECS["refund_count"].table == "refunds"
    assert METRIC_SPECS["refund_amount"].table == "refunds"
    assert METRIC_SPECS["return_count"].table == "returns"


def test_unknown_metric_raises_instead_of_returning_none() -> None:
    """静默返回 None 会让调用方在下一步才炸，错误信息离现场很远。"""

    with pytest.raises(UnknownFieldError):
        metric_spec("gmv; DROP TABLE orders")


def test_unknown_dimension_raises() -> None:
    with pytest.raises(UnknownFieldError):
        dimension_spec("seller_secret")


def test_refund_reason_is_not_offered_for_gmv() -> None:
    """按退款原因拆 GMV 没有业务含义，也没有可用的连接路径。"""

    assert "refund_reason" not in compatible_dimensions(METRIC_SPECS["gmv"])
    assert "refund_reason" in compatible_dimensions(METRIC_SPECS["refund_amount"])


def test_date_is_compatible_with_every_metric() -> None:
    for spec in METRIC_SPECS.values():
        assert "date" in compatible_dimensions(spec), spec.code
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/unit/analytics/test_contract.py -q`

Expected: FAIL，`ModuleNotFoundError: No module named 'app.analytics.contract'`。

- [ ] **Step 3: 实现注册表**

`backend/app/analytics/contract.py`：

```python
"""指标与维度到数据库对象的唯一映射。

**用户输入永远不进入 SQL 的标识符位置。** 模型和用户只能给出 metric_code 与
dimension 名，能不能落到某张表某一列，完全由这张代码内注册表决定。B3 的意图
白名单是第一道，这里是第二道——计划把「查询层必须再校验一次」写成了硬要求。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

MetricKind = Literal["SIMPLE", "RATIO"]


class UnknownFieldError(LookupError):
    """请求了注册表之外的指标或维度。调用方应转成可展示的拒绝原因。"""


@dataclass(frozen=True)
class MetricSpec:
    code: str
    label: str
    unit: str
    #: 主表。RATIO 类指标的主表是分母所在表。
    table: str
    #: 能否跨区间相加。去重计数与比例为 False。
    additive: bool
    kind: MetricKind = "SIMPLE"


@dataclass(frozen=True)
class DimensionSpec:
    code: str
    label: str
    table: str
    column: str


METRIC_SPECS: Final[Mapping[str, MetricSpec]] = {
    "gmv": MetricSpec("gmv", "成交 GMV", "元", "orders", True),
    "order_count": MetricSpec("order_count", "订单量", "单", "orders", True),
    "paying_user_count": MetricSpec("paying_user_count", "付款用户数", "人", "orders", False),
    "successful_order_count": MetricSpec(
        "successful_order_count", "成功订单量", "单", "orders", True
    ),
    "refund_count": MetricSpec("refund_count", "退款量", "单", "refunds", True),
    "refund_amount": MetricSpec("refund_amount", "退款金额", "元", "refunds", True),
    "return_count": MetricSpec("return_count", "退货量", "件", "returns", True),
    "return_rate": MetricSpec("return_rate", "退货率", "%", "order_items", False, "RATIO"),
    "support_ticket_count": MetricSpec(
        "support_ticket_count", "客服工单量", "单", "support_tickets", True
    ),
}

DIMENSION_SPECS: Final[Mapping[str, DimensionSpec]] = {
    "date": DimensionSpec("date", "日期", "", "business_date"),
    "product": DimensionSpec("product", "商品", "products", "title"),
    "category": DimensionSpec("category", "类目", "products", "category"),
    "order_status": DimensionSpec("order_status", "订单状态", "orders", "order_status"),
    "refund_reason": DimensionSpec("refund_reason", "退款原因", "refunds", "refund_reason"),
    "return_reason": DimensionSpec("return_reason", "退货原因", "returns", "return_reason"),
    "return_status": DimensionSpec("return_status", "退货状态", "returns", "return_status"),
    "ticket_status": DimensionSpec("ticket_status", "工单状态", "support_tickets", "ticket_status"),
}

#: 每张主表能连到哪些维度表。空字符串代表「用主表自己的列」（date）。
_COMPATIBLE: Final[Mapping[str, frozenset[str]]] = {
    "orders": frozenset({"", "orders", "products"}),
    "refunds": frozenset({"", "refunds"}),
    "returns": frozenset({"", "returns"}),
    "order_items": frozenset({"", "products"}),
    "support_tickets": frozenset({"", "support_tickets"}),
}


def metric_spec(code: str) -> MetricSpec:
    try:
        return METRIC_SPECS[code]
    except KeyError as error:
        raise UnknownFieldError(f"指标 {code} 不在受控查询契约内") from error


def dimension_spec(code: str) -> DimensionSpec:
    try:
        return DIMENSION_SPECS[code]
    except KeyError as error:
        raise UnknownFieldError(f"维度 {code} 不在受控查询契约内") from error


def compatible_dimensions(metric: MetricSpec) -> frozenset[str]:
    """该指标可用的维度集合。不兼容的组合由调用方显式拒绝，不静默忽略。"""

    tables = _COMPATIBLE[metric.table]
    return frozenset(code for code, spec in DIMENSION_SPECS.items() if spec.table in tables)
```

- [ ] **Step 4: 把指标口径写进 Seed**

`backend/app/metrics/seed.py` 的 `_item` 目前把 `sql_definition` 写成占位 `SUM(code)`，用户在口径面板会看到一个假的公式。改为逐条给出真实口径（`business_definition` 保持中文说明，`sql_definition` 给算法）：

```python
METRIC_SEED: Final[tuple[MetricSeedItem, ...]] = (
    MetricSeedItem(
        "gmv",
        "成交 GMV",
        "元",
        "统计周期内已支付订单金额之和。",
        "SUM(orders.paid_amount) WHERE order_status IN ('PAID','SHIPPED','COMPLETED')",
    ),
    MetricSeedItem(
        "order_count", "订单量", "单", "统计周期内创建的订单数量。", "COUNT(orders.id)"
    ),
    MetricSeedItem(
        "paying_user_count",
        "付款用户数",
        "人",
        "统计周期内完成付款的去重用户数。",
        "COUNT(DISTINCT orders.buyer_key) WHERE paid_at IS NOT NULL",
    ),
    MetricSeedItem(
        "successful_order_count",
        "成功订单量",
        "单",
        "统计周期内交易成功的订单数量。",
        "COUNT(orders.id) WHERE order_status = 'COMPLETED'",
    ),
    MetricSeedItem(
        "refund_count",
        "退款量",
        "单",
        "统计周期内发起退款的订单数量。",
        "COUNT(refunds.id) WHERE refund_status IN ('APPROVED','REFUNDED')",
    ),
    MetricSeedItem(
        "refund_amount",
        "退款金额",
        "元",
        "统计周期内退款总金额。",
        "SUM(refunds.refund_amount) WHERE refund_status = 'REFUNDED'",
    ),
    MetricSeedItem(
        "return_count",
        "退货量",
        "件",
        "统计周期内发起退货的商品件数。",
        "SUM(returns.return_quantity)",
    ),
    MetricSeedItem(
        "return_rate",
        "退货率",
        "%",
        "退货件数除以同期订单项件数，按查询区间重新计算，不可跨日相加。",
        "SUM(returns.return_quantity) / NULLIF(SUM(order_items.quantity), 0)",
    ),
    MetricSeedItem(
        "support_ticket_count",
        "客服工单量",
        "单",
        "统计周期内创建的客服工单数量。",
        "COUNT(support_tickets.id)",
    ),
)
```

删除现在的 `_item` 辅助函数（它的存在就是为了生成占位公式）。

- [ ] **Step 5: 写迁移刷新已有库里的口径**

`backend/migrations/versions/20260804_0006_metric_sql_definition.py`：

```python
"""Refresh metric sql_definition with the B4 query contract.

Historical migrations must stay reproducible, so the new values are inlined
here instead of imported from ``app.metrics.seed``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0006"
down_revision: str | Sequence[str] | None = "20260804_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("gmv", "SUM(orders.paid_amount) WHERE order_status IN ('PAID','SHIPPED','COMPLETED')"),
    ("order_count", "COUNT(orders.id)"),
    ("paying_user_count", "COUNT(DISTINCT orders.buyer_key) WHERE paid_at IS NOT NULL"),
    ("successful_order_count", "COUNT(orders.id) WHERE order_status = 'COMPLETED'"),
    ("refund_count", "COUNT(refunds.id) WHERE refund_status IN ('APPROVED','REFUNDED')"),
    ("refund_amount", "SUM(refunds.refund_amount) WHERE refund_status = 'REFUNDED'"),
    ("return_count", "SUM(returns.return_quantity)"),
    ("return_rate", "SUM(returns.return_quantity) / NULLIF(SUM(order_items.quantity), 0)"),
    ("support_ticket_count", "COUNT(support_tickets.id)"),
)


def upgrade() -> None:
    for code, definition in _DEFINITIONS:
        op.execute(
            sa.text(
                "UPDATE metric_definitions SET sql_definition = :definition "
                "WHERE metric_code = :code"
            ).bindparams(definition=definition, code=code)
        )


def downgrade() -> None:
    for code, _ in _DEFINITIONS:
        op.execute(
            sa.text(
                "UPDATE metric_definitions SET sql_definition = :definition "
                "WHERE metric_code = :code"
            ).bindparams(definition=f"SUM({code})", code=code)
        )
```

- [ ] **Step 6: 跑测试与门禁**

Run: `cd backend && uv run pytest tests/unit/analytics/ tests/unit/intent/ -q`，Expected: PASS。

---

### Task 4: 业务时区与日期范围解析

**Files:**
- Create: `backend/app/analytics/dates.py`
- Modify: `backend/app/core/config.py`（新增 `business_timezone`）
- Test: `backend/tests/unit/analytics/test_dates.py`

**Interfaces:**
- Produces: `business_today(now: datetime, *, timezone: str) -> date`。
- Produces: `resolve_range(requested: DateRange | None, *, now: datetime, timezone: str) -> tuple[DateRange, tuple[str, ...]]`，返回最终区间与「已调整」说明。
- Produces: `DEFAULT_RANGE_DAYS: int = 7`。
- Consumes: `app.intent.models.DateRange`、`app.intent.whitelist.MAX_QUERY_DAYS`。

B3 的 `validate_intent` 已经按注入的 `today` 截断过一次；这里负责的是另一件事：**模型没给日期时给出默认区间**，以及把「今天」的判定收敛到业务时区一处。两处都做截断不是重复——B3 拦的是模型的越界输出，这里保证进 SQL 的区间一定合法。

- [ ] **Step 1: 写失败的时区测试**

`backend/tests/unit/analytics/test_dates.py`：

```python
"""业务日界与日期范围解析。

时钟必须可注入：跨零点归属是这一层最容易错、也最难靠人工复现的地方。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.analytics.dates import DEFAULT_RANGE_DAYS, business_today, resolve_range
from app.intent.models import DateRange
from app.intent.whitelist import MAX_QUERY_DAYS

TZ = "Asia/Shanghai"


def test_utc_evening_still_belongs_to_the_same_business_day() -> None:
    """UTC 15:30 是北京时间 23:30，仍算当天。"""

    assert business_today(datetime(2026, 8, 4, 15, 30, tzinfo=UTC), timezone=TZ) == date(2026, 8, 4)


def test_utc_after_16_rolls_over_to_the_next_business_day() -> None:
    """UTC 16:30 已是北京时间次日 00:30。按 UTC 判定会把「昨天」整体错位一天。"""

    assert business_today(datetime(2026, 8, 4, 16, 30, tzinfo=UTC), timezone=TZ) == date(2026, 8, 5)


def test_missing_range_defaults_to_the_recent_window() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)

    resolved, notes = resolve_range(None, now=now, timezone=TZ)

    assert resolved.end == date(2026, 8, 4)
    assert (resolved.end - resolved.start).days + 1 == DEFAULT_RANGE_DAYS
    assert any("默认" in note for note in notes)


def test_requested_range_is_preserved_when_legal() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2026, 7, 1), end=date(2026, 7, 31))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert resolved == requested
    assert notes == ()


def test_future_end_is_clamped_to_the_business_today() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2026, 8, 1), end=date(2026, 12, 31))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert resolved.end == date(2026, 8, 4)
    assert any("未来" in note for note in notes)


def test_range_longer_than_the_maximum_is_clamped() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2024, 1, 1), end=date(2026, 8, 4))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert (resolved.end - resolved.start).days + 1 == MAX_QUERY_DAYS
    assert any(str(MAX_QUERY_DAYS) in note for note in notes)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/unit/analytics/test_dates.py -q`，Expected: FAIL（模块不存在）。

- [ ] **Step 3: 加配置项**

`backend/app/core/config.py` 的 `Settings` 中，`db_statement_timeout_ms` 之后追加：

```python
    #: 业务时区。日界、「昨天」和日报区间都按它计算，不是 per-merchant 字段。
    business_timezone: str = "Asia/Shanghai"
```

- [ ] **Step 4: 实现日期解析**

`backend/app/analytics/dates.py`：

```python
"""业务日界与查询区间解析。

时钟从参数进来，不在这里读——「昨天」跨零点的归属必须能被冻结时钟测试覆盖。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.intent.models import DateRange
from app.intent.whitelist import MAX_QUERY_DAYS

#: 模型没给日期时的默认窗口。演示数据覆盖 180 天，7 天是最常见的经营问法。
DEFAULT_RANGE_DAYS: Final[int] = 7


def business_today(now: datetime, *, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def resolve_range(
    requested: DateRange | None,
    *,
    now: datetime,
    timezone: str,
) -> tuple[DateRange, tuple[str, ...]]:
    """产出一定合法的查询区间，并说明做过哪些调整。"""

    today = business_today(now, timezone=timezone)
    notes: list[str] = []

    if requested is None:
        start = today - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        notes.append(f"问题未指定时间范围，默认查询最近 {DEFAULT_RANGE_DAYS} 天")
        return DateRange(start=start, end=today), tuple(notes)

    start, end = requested.start, requested.end
    if end > today:
        end = today
        notes.append("结束日期在未来，已截断到今天")
    if start > end:
        start = end
        notes.append("起始日期晚于结束日期，已收敛为单日")
    if (end - start).days + 1 > MAX_QUERY_DAYS:
        start = end - timedelta(days=MAX_QUERY_DAYS - 1)
        notes.append(f"查询范围超过 {MAX_QUERY_DAYS} 天，已截断为最近 {MAX_QUERY_DAYS} 天")

    return DateRange(start=start, end=end), tuple(notes)
```

- [ ] **Step 5: 跑测试与门禁**

Run: `cd backend && uv run pytest tests/unit/analytics/ -q`，Expected: PASS。

---

### Task 5: Analytics Repository · 指标聚合

**Files:**
- Create: `backend/app/repositories/analytics.py`
- Test: `backend/tests/integration/repositories/test_analytics_repository.py`

**Interfaces:**
- Consumes: Task 1 ORM、Task 3 注册表。
- Produces: `@dataclass(frozen=True) ResultColumn(key: str, label: str, kind: Literal["DIMENSION","METRIC"])`。
- Produces: `@dataclass(frozen=True) AggregateResult(columns, rows, source_tables)`，`rows: list[dict[str, object]]`。
- Produces: `AnalyticsRepository(session).aggregate(*, merchant_id, metric, dimensions, filters, start, end, limit, sort=None) -> AggregateResult`。`sort` 只接受 `None`、`"<key>"`（升序）或 `"-<key>"`（降序），`key` 必须是本次查询的指标码或维度码，由调用方先校验。

- [ ] **Step 1: 写失败的集成测试**

`backend/tests/integration/repositories/test_analytics_repository.py`：

```python
"""受控聚合查询。

用真实 PostgreSQL：这一层的价值全在 SQL 本身（隔离、聚合、分组、比例重算），
用假仓储测等于什么都没测。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import METRIC_SPECS
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord
from app.repositories.analytics import AnalyticsRepository

DAY = date(2026, 8, 3)
NEXT_DAY = date(2026, 8, 4)


async def _fixture_rows(session: AsyncSession, merchant_id: UUID) -> UUID:
    """两天各一单，第二天那单退货 2 件、退款一笔。返回第一天的订单项 id。"""

    product = Product(
        merchant_id=merchant_id,
        business_date=DAY,
        product_code=f"SKU-{uuid4().hex[:8]}",
        title="演示商品",
        category="女装",
        price=Decimal("100.00"),
        status="ONLINE",
        listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc),
    )
    session.add(product)
    await session.flush()

    first_item_id = uuid4()
    for index, (day, quantity) in enumerate(((DAY, 4), (NEXT_DAY, 6))):
        order = Order(
            merchant_id=merchant_id,
            business_date=day,
            order_no=f"NO-{uuid4().hex[:10]}",
            buyer_key=f"buyer-{index}",
            order_status="COMPLETED",
            total_amount=Decimal("100.00") * quantity,
            paid_amount=Decimal("100.00") * quantity,
            placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc),
            paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc),
        )
        session.add(order)
        await session.flush()
        item = OrderItem(
            id=first_item_id if index == 0 else uuid4(),
            merchant_id=merchant_id,
            business_date=day,
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            item_amount=Decimal("100.00") * quantity,
        )
        session.add(item)
        await session.flush()
        if index == 1:
            session.add(
                ReturnRecord(
                    merchant_id=merchant_id,
                    business_date=NEXT_DAY,
                    order_item_id=item.id,
                    return_quantity=2,
                    return_reason="尺码不合适",
                    return_status="COMPLETED",
                    logistics_status="DELIVERED",
                    returned_at=datetime(2026, 8, 4, 3, 0, tzinfo=timezone.utc),
                )
            )
            session.add(
                Refund(
                    merchant_id=merchant_id,
                    business_date=NEXT_DAY,
                    order_item_id=item.id,
                    refund_amount=Decimal("200.00"),
                    refund_reason="尺码不合适",
                    refund_status="REFUNDED",
                    refunded_at=datetime(2026, 8, 4, 4, 0, tzinfo=timezone.utc),
                )
            )
    await session.flush()
    return first_item_id


@pytest.mark.asyncio
async def test_aggregate_sums_gmv_over_the_range(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": Decimal("1000.00")}]
    assert result.source_tables == ("orders",)


@pytest.mark.asyncio
async def test_aggregate_groups_by_date_in_stable_order(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=("date",),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert [row["date"] for row in result.rows] == [DAY, NEXT_DAY]
    assert [column.key for column in result.columns] == ["date", "gmv"]
    assert [column.label for column in result.columns] == ["日期", "成交 GMV"]


@pytest.mark.asyncio
async def test_other_merchants_rows_are_never_visible(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    """没有这条，B4 就是把 B1 建立的隔离在查询层重新打开。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_two_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": None}]


@pytest.mark.asyncio
async def test_return_rate_is_recomputed_over_the_interval(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """退货 2 件 ÷ 同期订单项 10 件 = 20%。按日均会算成 (0% + 33.3%)/2 = 16.7%。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["return_rate"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows[0]["return_rate"] == pytest.approx(Decimal("0.20"), abs=Decimal("0.001"))


@pytest.mark.asyncio
async def test_return_count_reads_returns_not_refunds(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """「退货量」返回 2 件而不是 200 元——这正是分表要防的混淆。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    returned = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["return_count"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )
    refunded = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["refund_amount"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert returned.rows == [{"return_count": 2}]
    assert refunded.rows == [{"refund_amount": Decimal("200.00")}]


@pytest.mark.asyncio
async def test_filter_values_are_bound_not_interpolated(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """注入串必须被当成普通字符串值，命中零行而不是改变语义。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={"category": "女装' OR '1'='1"},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": None}]
```

需要 `merchant_one_id` / `merchant_two_id` 夹具。`tests/conftest.py` 已有 `MERCHANT_ONE_ID` / `MERCHANT_TWO_ID` 常量与建商家的夹具——若没有同名夹具，在 `tests/conftest.py` 追加：

```python
@pytest.fixture
def merchant_one_id() -> UUID:
    return MERCHANT_ONE_ID


@pytest.fixture
def merchant_two_id() -> UUID:
    return MERCHANT_TWO_ID
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/integration/repositories/test_analytics_repository.py -q`

Expected: FAIL（模块不存在）。若本地没起 PostgreSQL，先启动测试库再跑——本 Task 不允许以跳过收尾。

- [ ] **Step 3: 实现聚合仓储**

`backend/app/repositories/analytics.py`：

```python
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
from typing import Literal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import (
    DimensionSpec,
    MetricSpec,
    UnknownFieldError,
    dimension_spec,
)
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket

_TABLES = {
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


def _metric_expression(metric: MetricSpec):  # noqa: ANN202 - SQLAlchemy 表达式类型不稳定
    if metric.code == "gmv":
        return func.sum(Order.paid_amount).filter(
            Order.order_status.in_(("PAID", "SHIPPED", "COMPLETED"))
        )
    if metric.code == "order_count":
        return func.count(Order.id)
    if metric.code == "paying_user_count":
        return func.count(func.distinct(Order.buyer_key)).filter(Order.paid_at.is_not(None))
    if metric.code == "successful_order_count":
        return func.count(Order.id).filter(Order.order_status == "COMPLETED")
    if metric.code == "refund_count":
        return func.count(Refund.id).filter(Refund.refund_status.in_(("APPROVED", "REFUNDED")))
    if metric.code == "refund_amount":
        return func.sum(Refund.refund_amount).filter(Refund.refund_status == "REFUNDED")
    if metric.code == "return_count":
        return func.sum(ReturnRecord.return_quantity)
    if metric.code == "support_ticket_count":
        return func.count(SupportTicket.id)
    raise AssertionError(f"未实现的指标表达式：{metric.code}")


def _dimension_column(metric: MetricSpec, spec: DimensionSpec):  # noqa: ANN202
    if spec.code == "date":
        # date 用主表自己的业务日列；RATIO 指标的主表是分母所在的 order_items。
        return _TABLES[metric.table].business_date
    return getattr(_TABLES[spec.table], spec.column)


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

        metric_column = _metric_expression(metric).label(metric.code)
        statement: Select = select(
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
            source_tables=self._source_tables(metric, specs, filters),
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

        statement: Select = (
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
        metric_column,  # noqa: ANN001 - 已 label 的指标表达式
        metric: MetricSpec,
        specs: Sequence[DimensionSpec],
        group_columns: Sequence[object],
        sort: str | None,
    ):  # noqa: ANN202 - SQLAlchemy 表达式类型不稳定
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
        statement: Select,
        metric: MetricSpec,
        specs: Sequence[DimensionSpec],
        filters: Mapping[str, str],
    ) -> Select:
        """按需连接维度表。连接路径写死在代码里，不由入参决定。"""

        needed = {spec.table for spec in specs if spec.table} | {
            dimension_spec(code).table for code in filters if dimension_spec(code).table
        }
        if "products" in needed and metric.table in {"orders", "order_items"}:
            if metric.table == "orders":
                statement = statement.join(OrderItem, OrderItem.order_id == Order.id)
            statement = statement.join(Product, Product.id == OrderItem.product_id)
        return statement

    def _apply_filters(
        self,
        statement: Select,
        metric: MetricSpec,
        filters: Mapping[str, str],
    ) -> Select:
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
    ) -> tuple[str, ...]:
        tables = {metric.table}
        tables |= {spec.table for spec in specs if spec.table}
        tables |= {dimension_spec(code).table for code in filters if dimension_spec(code).table}
        return tuple(sorted(tables))
```

- [ ] **Step 4: 跑测试**

Run: `cd backend && uv run pytest tests/integration/repositories/test_analytics_repository.py -q`

Expected: PASS，6 个测试。

- [ ] **Step 5: 门禁**

---

### Task 6: Analytics Repository · 明细查询

**Files:**
- Modify: `backend/app/repositories/analytics.py`
- Modify: `backend/app/analytics/contract.py`（新增明细表路由）
- Test: `backend/tests/integration/repositories/test_analytics_detail.py`

**Interfaces:**
- Produces: `DETAIL_SPECS: Mapping[str, DetailSpec]`，键为 `orders`、`refunds`、`returns`、`products`、`support_tickets`。
- Produces: `@dataclass(frozen=True) DetailSpec(table, label, columns: tuple[tuple[str, str], ...])`，`columns` 是 `(列名, 中文标签)` 的有序元组——**列顺序即展示顺序，且禁止 `SELECT *`**。
- Produces: `@dataclass(frozen=True) DetailResult(columns, rows, total_rows, truncated, source_tables)`。
- Produces: `AnalyticsRepository.detail(*, merchant_id, spec, filters, start, end, limit) -> DetailResult`。

- [ ] **Step 1: 写失败的明细测试**

`backend/tests/integration/repositories/test_analytics_detail.py`：

```python
"""明细查询的行数、截断与列顺序。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import DETAIL_SPECS
from app.models.analytics import Order
from app.repositories.analytics import AnalyticsRepository

DAY = date(2026, 8, 3)


async def _orders(session: AsyncSession, merchant_id: UUID, count: int) -> None:
    for index in range(count):
        session.add(
            Order(
                merchant_id=merchant_id,
                business_date=DAY,
                order_no=f"NO-{index:05d}-{uuid4().hex[:6]}",
                buyer_key=f"buyer-{index}",
                order_status="COMPLETED",
                total_amount=Decimal("10.00"),
                paid_amount=Decimal("10.00"),
                placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc),
                paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc),
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_detail_reports_total_rows_beyond_the_preview(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """预览截断但总数照实报，否则用户以为只有 200 单。"""

    await _orders(db_session, merchant_one_id, 205)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert len(result.rows) == 200
    assert result.total_rows == 205
    assert result.truncated is True


@pytest.mark.asyncio
async def test_detail_is_not_marked_truncated_when_it_fits(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _orders(db_session, merchant_one_id, 3)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.total_rows == 3
    assert result.truncated is False


@pytest.mark.asyncio
async def test_detail_columns_have_stable_order_and_chinese_labels(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """列顺序不稳定，前端表格每次刷新都会换列；缺中文标签则只能显示英文列名。"""

    await _orders(db_session, merchant_one_id, 1)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert [column.key for column in result.columns] == [
        name for name, _ in DETAIL_SPECS["orders"].columns
    ]
    assert all(column.label for column in result.columns)
    assert set(result.rows[0]) == {column.key for column in result.columns}


@pytest.mark.asyncio
async def test_detail_never_returns_other_merchants_rows(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    await _orders(db_session, merchant_one_id, 5)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_two_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.rows == []
    assert result.total_rows == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/integration/repositories/test_analytics_detail.py -q`，Expected: FAIL（`DETAIL_SPECS` 不存在）。

- [ ] **Step 3: 在 contract.py 增加明细契约**

追加到 `backend/app/analytics/contract.py`：

```python
@dataclass(frozen=True)
class DetailSpec:
    table: str
    label: str
    #: (列名, 中文标签) 的有序元组。顺序即展示顺序；显式列举也是「禁止 SELECT *」的落点。
    columns: tuple[tuple[str, str], ...]


DETAIL_SPECS: Final[Mapping[str, DetailSpec]] = {
    "orders": DetailSpec(
        "orders",
        "订单明细",
        (
            ("business_date", "日期"),
            ("order_no", "订单号"),
            ("order_status", "订单状态"),
            ("paid_amount", "实付金额"),
            ("placed_at", "下单时间"),
        ),
    ),
    "refunds": DetailSpec(
        "refunds",
        "退款明细",
        (
            ("business_date", "日期"),
            ("refund_amount", "退款金额"),
            ("refund_reason", "退款原因"),
            ("refund_status", "退款状态"),
            ("refunded_at", "退款时间"),
        ),
    ),
    "returns": DetailSpec(
        "returns",
        "退货明细",
        (
            ("business_date", "日期"),
            ("return_quantity", "退货件数"),
            ("return_reason", "退货原因"),
            ("return_status", "退货状态"),
            ("logistics_status", "物流状态"),
        ),
    ),
    "products": DetailSpec(
        "products",
        "商品明细",
        (
            ("business_date", "日期"),
            ("product_code", "商品编码"),
            ("title", "商品名称"),
            ("category", "类目"),
            ("price", "价格"),
            ("status", "状态"),
        ),
    ),
    "support_tickets": DetailSpec(
        "support_tickets",
        "工单明细",
        (
            ("business_date", "日期"),
            ("ticket_no", "工单号"),
            ("ticket_status", "工单状态"),
            ("ticket_reason", "工单类型"),
            ("opened_at", "创建时间"),
        ),
    ),
}

#: 业务分类到默认明细表的路由。没有对应经营表的域不出现在这里。
DETAIL_BY_CATEGORY: Final[Mapping[str, str]] = {
    "TRADE": "orders",
    "REFUND": "refunds",
    "CS_TICKET": "support_tickets",
    "GOODS": "products",
}


def detail_spec(table: str) -> DetailSpec:
    try:
        return DETAIL_SPECS[table]
    except KeyError as error:
        raise UnknownFieldError(f"明细 {table} 不在受控查询契约内") from error
```

- [ ] **Step 4: 实现明细查询**

追加到 `AnalyticsRepository`：

```python
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
        """预览有上限，总数照实报——只给 200 行却说「共 200 条」是撒谎。"""

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
            columns=tuple(
                ResultColumn(name, label, "DIMENSION") for name, label in spec.columns
            ),
            rows=rows,
            total_rows=total_rows,
            truncated=total_rows > len(rows),
            source_tables=(spec.table,),
        )
```

同时在文件顶部补 `DetailResult` 定义与 `DetailSpec`、`detail_spec` 的 import：

```python
@dataclass(frozen=True)
class DetailResult:
    columns: tuple[ResultColumn, ...]
    rows: list[dict[str, object]]
    total_rows: int
    truncated: bool
    source_tables: tuple[str, ...]
```

- [ ] **Step 5: 跑测试与门禁**

Run: `cd backend && uv run pytest tests/integration/ -q`，Expected: PASS。

---

### Task 7: Safe Query Service

**Files:**
- Create: `backend/app/services/safe_query.py`
- Test: `backend/tests/integration/services/test_safe_query.py`

**Interfaces:**
- Consumes: Task 3 契约、Task 4 日期解析、Task 5/6 仓储、`MerchantContext`、`QueryIntent`。
- Produces: `@dataclass(frozen=True) QueryResult(columns, rows, total_rows, truncated, source_tables, plan_steps, export_spec, notes, non_additive)`。
- Produces: `@dataclass(frozen=True) ExportSpec(table: str, columns: tuple[str, ...], start: date, end: date)`（B6 的导出据此生成 CSV，本阶段只产出描述，不落文件）。
- Produces: `class UnsupportedQueryError(Exception)`，带 `reason: str`（可安全展示）。
- Produces: `SafeQueryService(repository, settings).execute(context, intent, *, now) -> QueryResult`。

- [ ] **Step 1: 写失败的服务测试**

`backend/tests/integration/services/test_safe_query.py`：

```python
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
    with pytest.raises(UnsupportedQueryError):
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(dimensions=["refund_reason"]),
            now=NOW,
        )


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
    """排序键会进 ORDER BY 的标识符位置，和指标、维度是同一类风险。"""

    with pytest.raises(UnsupportedQueryError):
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(dimensions=["date"], sort="gmv; DROP TABLE orders"),
            now=NOW,
        )


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

    assert [row["gmv"] for row in result.rows][0] == Decimal("90.00")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/integration/services/test_safe_query.py -q`，Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现服务**

`backend/app/services/safe_query.py`：

```python
"""受控经营查询的编排层。

它决定「查什么」，Repository 决定「怎么查」。B3 的白名单在这里被第二次执行：
拿到注册表里不存在的键就拒绝，并给出可以直接展示给用户的原因——不透出表名、
列名和任何 SQL 片段。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from app.analytics.contract import (
    DETAIL_BY_CATEGORY,
    UnknownFieldError,
    compatible_dimensions,
    detail_spec,
    dimension_spec,
    metric_spec,
)
from app.analytics.dates import resolve_range
from app.core.security import MerchantContext
from app.intent.models import QueryIntent
from app.intent.whitelist import MAX_DETAIL_LIMIT
from app.repositories.analytics import AnalyticsRepository, ResultColumn
from app.schemas.chat import AnswerMode

_METRIC_PREVIEW_LIMIT: Final[int] = 200


class UnsupportedQueryError(Exception):
    """请求超出受控查询范围。`reason` 可以安全展示给用户。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ExportSpec:
    table: str
    columns: tuple[str, ...]
    start: date
    end: date


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[ResultColumn, ...]
    rows: list[dict[str, object]]
    total_rows: int
    truncated: bool
    source_tables: tuple[str, ...]
    plan_steps: tuple[str, ...]
    export_spec: ExportSpec | None
    notes: tuple[str, ...]
    #: True 表示结果里的指标不可跨行相加（去重计数、比例）。B5 据此避免错误求和。
    non_additive: bool


class SafeQueryService:
    def __init__(self, repository: AnalyticsRepository, *, business_timezone: str) -> None:
        self._repository = repository
        self._timezone = business_timezone

    async def execute(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        *,
        now: datetime,
    ) -> QueryResult:
        date_range, notes = resolve_range(
            intent.date_range, now=now, timezone=self._timezone
        )

        if intent.answer_mode is AnswerMode.DETAIL:
            return await self._detail(context, intent, date_range, notes)
        if intent.answer_mode is AnswerMode.METRIC:
            return await self._metric(context, intent, date_range, notes)
        raise UnsupportedQueryError(f"{intent.answer_mode.value} 模式不执行经营数据查询")

    async def _metric(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        date_range,  # noqa: ANN001 - DateRange
        notes: tuple[str, ...],
    ) -> QueryResult:
        if intent.metric is None:
            raise UnsupportedQueryError("问题没有指向具体指标，无法执行经营数据查询")
        try:
            metric = metric_spec(intent.metric)
        except UnknownFieldError as error:
            raise UnsupportedQueryError(f"指标 {intent.metric} 不在可查询范围内") from error

        allowed = compatible_dimensions(metric)
        for code in intent.dimensions:
            try:
                dimension_spec(code)
            except UnknownFieldError as error:
                raise UnsupportedQueryError(f"维度 {code} 不在可查询范围内") from error
            if code not in allowed:
                raise UnsupportedQueryError(f"{metric.label} 不支持按「{code}」拆分")
        for code in intent.filters:
            if code not in allowed:
                raise UnsupportedQueryError(f"{metric.label} 不支持按「{code}」筛选")

        sort = self._checked_sort(intent.sort, metric.code, tuple(intent.dimensions))

        result = await self._repository.aggregate(
            merchant_id=context.merchant_id,
            metric=metric,
            dimensions=tuple(intent.dimensions),
            filters=dict(intent.filters),
            start=date_range.start,
            end=date_range.end,
            limit=_METRIC_PREVIEW_LIMIT,
            sort=sort,
        )
        return QueryResult(
            columns=result.columns,
            rows=result.rows,
            total_rows=len(result.rows),
            truncated=False,
            source_tables=result.source_tables,
            plan_steps=self._plan_steps(metric.label, result.source_tables, date_range, notes),
            export_spec=None,
            notes=notes,
            non_additive=not metric.additive,
        )

    async def _detail(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        date_range,  # noqa: ANN001 - DateRange
        notes: tuple[str, ...],
    ) -> QueryResult:
        table = DETAIL_BY_CATEGORY.get(intent.category.value)
        if table is None:
            raise UnsupportedQueryError(f"「{intent.category.value}」暂无可查询的经营明细")
        spec = detail_spec(table)
        limit = min(intent.limit or MAX_DETAIL_LIMIT, MAX_DETAIL_LIMIT)

        result = await self._repository.detail(
            merchant_id=context.merchant_id,
            spec=spec,
            filters=dict(intent.filters),
            start=date_range.start,
            end=date_range.end,
            limit=limit,
        )
        return QueryResult(
            columns=result.columns,
            rows=result.rows,
            total_rows=result.total_rows,
            truncated=result.truncated,
            source_tables=result.source_tables,
            plan_steps=self._plan_steps(spec.label, result.source_tables, date_range, notes),
            export_spec=ExportSpec(
                table=spec.table,
                columns=tuple(name for name, _ in spec.columns),
                start=date_range.start,
                end=date_range.end,
            ),
            notes=notes,
            non_additive=False,
        )

    def _checked_sort(
        self,
        sort: str | None,
        metric_code: str,
        dimensions: tuple[str, ...],
    ) -> str | None:
        """排序键会进 ORDER BY 的标识符位置，和指标、维度是同一类风险。

        只接受本次查询已经产出的列码，前缀 `-` 表示降序。不认识的一律拒绝，
        不做「忽略掉继续查」——那样用户拿到的顺序和他要的不一样却没有提示。
        """

        if not sort:
            return None
        key = sort.lstrip("-")
        if key != metric_code and key not in dimensions:
            raise UnsupportedQueryError(f"不支持按「{key}」排序")
        return sort

    def _plan_steps(
        self,
        subject: str,
        source_tables: tuple[str, ...],
        date_range,  # noqa: ANN001 - DateRange
        notes: tuple[str, ...],
    ) -> tuple[str, ...]:
        """查询计划只承载可安全展示的描述，不含 SQL 与数据行。"""

        return (
            f"按商家范围检索{subject}",
            f"时间范围 {date_range.start:%Y-%m-%d} 至 {date_range.end:%Y-%m-%d}",
            f"数据来源：{'、'.join(source_tables)}",
            *notes,
        )
```

- [ ] **Step 4: 跑测试与门禁**

Run: `cd backend && uv run pytest tests/integration/services/test_safe_query.py -q`，Expected: PASS，7 个测试。

---

### Task 8: `GET /api/metrics/{code}` 指标口径端点

**Files:**
- Create: `backend/app/schemas/metric.py`
- Create: `backend/app/api/routes/metrics.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/api/test_metrics.py`

**Interfaces:**
- Produces: `class MetricDefinitionResponse(BaseModel)`，字段 `metric_code`、`display_name`、`unit`、`definition`、`source`、`owner`、`status: MetricStatus`。
- Produces: `GET /api/metrics/{code}`，认证 `M`，错误码 401 / 404。

- [ ] **Step 1: 写失败的接口测试**

`backend/tests/api/test_metrics.py`：

```python
"""指标口径端点。PRD 要求口径面板展示来源、负责人和状态三项，缺一前端只能留白。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import MERCHANT_ONE_AUTH


@pytest.mark.asyncio
async def test_known_metric_returns_the_full_definition(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/metrics/gmv", headers=MERCHANT_ONE_AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["metric_code"] == "gmv"
    assert payload["display_name"] == "成交 GMV"
    assert payload["unit"] == "元"
    assert payload["source"]
    assert payload["owner"]
    assert payload["status"] in {"ACTIVE", "DEPRECATED", "UNVERIFIED"}


@pytest.mark.asyncio
async def test_unknown_metric_returns_404_error_contract(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/metrics/not_a_metric", headers=MERCHANT_ONE_AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_missing_token_is_rejected(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/metrics/gmv")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
```

`seeded_client` 是已有的、写入了演示商家与指标 Seed 的夹具；若 `tests/conftest.py` 里的等价夹具是别的名字，沿用现有名字，不要新建。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/api/test_metrics.py -q`，Expected: FAIL（404，路由不存在）。

- [ ] **Step 3: 写 Schema**

`backend/app/schemas/metric.py`：

```python
"""指标口径响应。"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.chat import MetricStatus


class MetricDefinitionResponse(BaseModel):
    metric_code: str
    display_name: str
    unit: str
    definition: str
    source: str
    owner: str
    status: MetricStatus
```

- [ ] **Step 4: 写路由**

`backend/app/api/routes/metrics.py`：

```python
"""指标口径端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, require_merchant_context
from app.core.errors import AppError, ErrorCode
from app.core.errors import error_responses
from app.core.security import MerchantContext
from app.repositories.metric import MetricRepository
from app.schemas.metric import MetricDefinitionResponse

router = APIRouter(tags=["metrics"])


@router.get(
    "/metrics/{code}",
    response_model=MetricDefinitionResponse,
    responses=error_responses(401, 404),
)
async def get_metric_definition(
    code: str,
    context: Annotated[MerchantContext, Depends(require_merchant_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MetricDefinitionResponse:
    """返回正式指标口径。指标目录对所有商家一致，因此不按商家过滤。"""

    del context  # 认证仍然必需：口径属于产品资料，不对匿名访问开放。
    definition = await MetricRepository(session).get_by_code(code)
    if definition is None:
        raise AppError(code=ErrorCode.NOT_FOUND, status_code=404, message="指标口径不存在")
    return MetricDefinitionResponse(
        metric_code=definition.metric_code,
        display_name=definition.display_name,
        unit=definition.unit,
        definition=definition.business_definition,
        source=definition.source,
        owner=definition.owner,
        status=definition.status,  # type: ignore[arg-type]
    )
```

依赖名 `require_merchant_context` 以 `app/api/dependencies.py` 里现有的商家认证依赖为准（chat 路由用的是哪个就用哪个），`AppError` 的构造签名同样以现有用法为准——**先读 `app/api/routes/chat.py` 里的写法再落笔**。

- [ ] **Step 5: 挂上路由**

`backend/app/api/router.py`：

```python
from app.api.routes.metrics import router as metrics_router

api_router.include_router(metrics_router)
```

- [ ] **Step 6: 重新导出 OpenAPI 并同步前端类型**

```bash
cd backend && uv run python ../scripts/export_openapi.py
cd ../frontend && npm run codegen && npm run codegen:check
```

Expected: `docs/api.json`、`docs/api.md` 与 `frontend/src/api/generated.ts` 同步更新，漂移检查通过。

- [ ] **Step 7: 跑测试与门禁**

Run: `cd backend && uv run pytest tests/api/ -q`，Expected: PASS。

---

### Task 9: 把真实数据接回问答图

**Files:**
- Modify: `backend/app/agent/graph.py`
- Modify: `backend/app/agent/state.py`
- Modify: `backend/app/api/dependencies.py`
- Test: `backend/tests/unit/agent/test_graph_query_data.py`

**Interfaces:**
- Consumes: Task 7 的 `SafeQueryService`、`QueryResult`、`UnsupportedQueryError`。
- Produces: `MerchantQaGraph.__init__` 新增关键字参数 `query_service: QueryServiceLike | None`、`merchant_id: UUID | None`。
- Produces: `AgentState` 新增 `query_result: QueryResult | None`、`query_error: str | None`。

这是 B4 唯一让用户看到变化的地方：`query_data` 节点从占位变成真查询，METRIC / DETAIL 回答从 `FALLBACK` + 「B4 接入」变成真实数据行。**回答正文、图表和建议仍属 B5**，本 Task 只把数据、总数、截断标记和查询计划填进去。

- [ ] **Step 1: 写失败的图测试**

`backend/tests/unit/agent/test_graph_query_data.py`：

```python
"""query_data 节点接入真实查询后的行为。

用假的查询服务：图这一层要验证的是「拿到结果怎么填响应」，SQL 正确性由
tests/integration 的仓储测试负责。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.repositories.analytics import ResultColumn
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus
from app.services.safe_query import QueryResult, UnsupportedQueryError


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _NoMetric:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _StubQueryService:
    def __init__(self, result: QueryResult | Exception) -> None:
        self._result = result
        self.calls = 0

    async def execute(self, context: object, intent: object, *, now: object) -> QueryResult:
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _metric_result() -> QueryResult:
    return QueryResult(
        columns=(ResultColumn("date", "日期", "DIMENSION"), ResultColumn("gmv", "成交 GMV", "METRIC")),
        rows=[{"date": date(2026, 8, 3), "gmv": Decimal("1200.00")}],
        total_rows=1,
        truncated=False,
        source_tables=("orders",),
        plan_steps=("按商家范围检索成交 GMV",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def _llm() -> FakeLlmClient:
    return FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": ["date"],
                    "filters": {},
                    "date_range": {"start": "2026-08-03", "end": "2026-08-03"},
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )


def _graph(service: _StubQueryService) -> MerchantQaGraph:
    llm = _llm()
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        query_service=service,
        merchant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_metric_answer_carries_real_rows_and_drops_the_b4_fallback() -> None:
    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert service.calls == 1
    assert result.response.data_rows == [{"date": "2026-08-03", "gmv": "1200.00"}]
    assert result.response.total_rows == 1
    assert result.response.analysis_sources == [AnalysisSource.DATABASE]
    assert result.response.degraded is False


@pytest.mark.asyncio
async def test_query_plan_summary_comes_from_the_query_not_a_placeholder() -> None:
    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert result.response.query_plan is not None
    assert "成交 GMV" in result.response.query_plan.summary


@pytest.mark.asyncio
async def test_refused_query_degrades_visibly_instead_of_faking_data() -> None:
    """查询被拒时绝不能返回空数组假装「没有数据」。"""

    service = _StubQueryService(UnsupportedQueryError("指标 seller_secret 不在可查询范围内"))

    result = await _graph(service).run("查个不存在的指标", uuid4())

    assert result.response.degraded is True
    assert "不在可查询范围内" in (result.response.degraded_reason or "")
    assert result.response.analysis_sources == [AnalysisSource.FALLBACK]
    assert result.response.quality_status is QualityStatus.DEGRADED


@pytest.mark.asyncio
async def test_no_query_service_keeps_the_previous_degradation_path() -> None:
    """未注入查询服务（例如单测环境）时，行为退回 B3 的可见降级，而不是崩溃。"""

    llm = _llm()
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
    )

    result = await graph.run("昨天 GMV", uuid4())

    assert result.response.answer_mode is AnswerMode.METRIC
    assert result.response.degraded is True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && uv run pytest tests/unit/agent/test_graph_query_data.py -q`

Expected: FAIL，`MerchantQaGraph.__init__() got an unexpected keyword argument 'query_service'`。

- [ ] **Step 3: 扩展 AgentState**

`backend/app/agent/state.py` 追加两个字段（并 import `QueryResult`）：

```python
    query_result: QueryResult | None
    query_error: str | None
```

`_initial_state` 里都初始化为 `None`。

- [ ] **Step 4: 让 `query_data` 真的查数**

`backend/app/agent/graph.py`：

构造函数追加两个可选参数并存下来：

```python
        query_service: QueryServiceLike | None = None,
        merchant_id: UUID | None = None,
```

其中 `QueryServiceLike` 是本文件内的 Protocol：

```python
class QueryServiceLike(Protocol):
    async def execute(
        self, context: MerchantContext, intent: QueryIntent, *, now: datetime
    ) -> QueryResult: ...
```

替换占位节点：

```python
    async def _query_data(self, state: AgentState) -> dict[str, object]:
        intent = _required(state["intent"])
        if self._query_service is None or self._merchant_id is None:
            # 未注入查询服务时保持 B3 的可见降级，而不是假装查过。
            return self._step(state, "query_data")
        if intent.answer_mode not in {AnswerMode.METRIC, AnswerMode.DETAIL}:
            return self._step(state, "query_data")

        try:
            result = await self._query_service.execute(
                MerchantContext(merchant_id=self._merchant_id),
                intent,
                now=datetime.now(UTC),
            )
        except UnsupportedQueryError as error:
            return {
                **self._step(state, "query_data"),
                "query_error": error.reason,
                "quality_notes": [*state["quality_notes"], error.reason],
            }
        return {
            **self._step(state, "query_data"),
            "query_result": result,
            "quality_notes": [*state["quality_notes"], *result.notes],
        }
```

`_response` 的 METRIC 分支改为：有 `query_result` 时用真实数据，`analysis_sources=[DATABASE]`、`degraded=False`、`quality_status=NOT_RUN`（Reviewer 属 B5）、`query_plan` 用 `plan_steps` 拼成摘要、`data_rows` 用下面的序列化函数；没有 `query_result` 时保留现有的 `FALLBACK` 降级路径，并在有 `query_error` 时把它作为 `degraded_reason`。DETAIL 分支同理，并用真实 `total_rows` / `truncated`。

`data_rows` 的序列化必须显式处理 `Decimal` 与 `date`——它们不能直接进 JSON：

```python
def _json_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Decimal 转字符串保精度，日期转 ISO 8601。float 会丢分。"""

    converted: list[dict[str, object]] = []
    for row in rows:
        converted.append(
            {
                key: (
                    str(value)
                    if isinstance(value, Decimal)
                    else value.isoformat()
                    if isinstance(value, date | datetime)
                    else value
                )
                for key, value in row.items()
            }
        )
    return converted
```

- [ ] **Step 5: 在依赖注入里接线**

`backend/app/api/dependencies.py` 的 `get_chat_service` 里构造 `SafeQueryService` 并传进图。商家 ID 必须来自已解析的 `MerchantContext`——**不要从请求体或查询参数取**：

```python
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(KnowledgeRepository(session)),
        intent_service_llm=llm,
        catalog=MetricCatalog(MetricRepository(session), llm),
        max_llm_calls=settings.llm_max_calls_per_request,
        max_llm_tokens=settings.llm_max_tokens_per_request,
        query_service=SafeQueryService(
            AnalyticsRepository(session), business_timezone=settings.business_timezone
        ),
        merchant_id=context.merchant_id,
    )
```

若 `get_chat_service` 当前没有拿到 `MerchantContext`，把认证依赖加进它的签名（chat 路由已经在用同一个依赖，不会多一次解析）。

- [ ] **Step 6: 跑测试**

Run: `cd backend && uv run pytest tests/unit/agent/ -q`，Expected: PASS。

- [ ] **Step 7: 重新导出 Chat Fixture**

数据接进来之后，`docs/fixtures/chat/` 里 METRIC / DETAIL 两个 fixture 的载荷会变（`analysis_sources` 由 `FALLBACK` 变 `DATABASE`、`data_rows` 非空）：

```bash
cd backend && uv run python ../scripts/export_chat_fixtures.py
cd ../frontend && npm run fixtures && npm run fixtures:check && npm run test
```

Expected: 漂移检查通过，前端单测全绿。若前端契约测试因 `analysis_sources` 变化而失败，**修测试的期望值，不要改后端去迁就旧 fixture**。

- [ ] **Step 8: 门禁**

---

### Task 10: 安全回归与端到端验收

**Files:**
- Create: `backend/tests/integration/services/test_safe_query_security.py`
- Modify: `backend/tests/integration/test_migrations.py`（如需覆盖新表）

**Interfaces:** 无新增，全部是验收测试。

- [ ] **Step 1: 写安全回归测试**

`backend/tests/integration/services/test_safe_query_security.py`：

```python
"""B4 的安全验收。

每条对应计划 §B4 验收里的一行。这些性质一旦回归，泄漏和注入是静默发生的，
所以必须有独立用例，不能依赖上层测试顺带覆盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.models.analytics import Order
from app.repositories.analytics import AnalyticsRepository
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.safe_query import SafeQueryService, UnsupportedQueryError

NOW = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
DAY = date(2026, 8, 3)


def _service(session: AsyncSession) -> SafeQueryService:
    return SafeQueryService(AnalyticsRepository(session), business_timezone="Asia/Shanghai")


async def _order(session: AsyncSession, merchant_id: UUID, amount: str) -> None:
    session.add(
        Order(
            merchant_id=merchant_id,
            business_date=DAY,
            order_no=f"NO-{uuid4().hex[:8]}",
            buyer_key="buyer",
            order_status="COMPLETED",
            total_amount=Decimal(amount),
            paid_amount=Decimal(amount),
            placed_at=NOW,
            paid_at=NOW,
        )
    )
    await session.flush()


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


@pytest.mark.asyncio
async def test_two_merchants_same_day_data_never_mix(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    await _order(db_session, merchant_one_id, "100.00")
    await _order(db_session, merchant_two_id, "999.00")

    first = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id), _intent(), now=NOW
    )
    second = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_two_id), _intent(), now=NOW
    )

    assert first.rows == [{"gmv": Decimal("100.00")}]
    assert second.rows == [{"gmv": Decimal("999.00")}]


@pytest.mark.asyncio
async def test_injection_in_filter_value_does_not_change_query_semantics(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _order(db_session, merchant_one_id, "100.00")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(filters={"order_status": "COMPLETED'; DROP TABLE orders; --"}),
        now=NOW,
    )

    assert result.rows == [{"gmv": None}]
    survived = await db_session.scalar(text("SELECT count(*) FROM orders"))
    assert survived == 1


@pytest.mark.asyncio
async def test_injection_in_metric_name_is_refused_before_reaching_sql(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    with pytest.raises(UnsupportedQueryError):
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(metric="gmv; DROP TABLE orders"),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_date_range_is_capped_at_180_days(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(date_range=DateRange(start=date(2024, 1, 1), end=DAY)),
        now=NOW,
    )

    assert any("180" in step for step in result.plan_steps)


@pytest.mark.asyncio
async def test_error_reason_never_leaks_sql_or_table_names(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """数据库细节泄漏给用户既没用，又给攻击者送情报。"""

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(metric="unknown_metric"),
            now=NOW,
        )

    reason = error.value.reason
    assert "orders" not in reason
    assert "SELECT" not in reason.upper()
    assert "psycopg" not in reason.lower()


@pytest.mark.asyncio
async def test_statement_timeout_is_active_on_the_request_session(
    db_session: AsyncSession,
) -> None:
    """没有 statement timeout，一条慢查询就能把连接池占满。

    直接问数据库当前会话的设置，而不是相信配置文件——`connect_args` 写错了
    也不会有任何报错，只会在某天变成一次线上事故。
    """

    timeout = await db_session.scalar(text("SHOW statement_timeout"))

    assert timeout not in {"0", "0ms", None}
```

- [ ] **Step 2: 运行并修到全绿**

Run: `cd backend && uv run pytest tests/integration/ -q`

- [ ] **Step 3: 在真实库上跑一次完整验收**

```bash
cd backend
uv run alembic upgrade head
uv run python scripts/seed_demo_analytics.py
uv run pytest
```

逐条核对计划 §B4 的验收清单，把结果写进 `docs/project-progress.md`：

- 用户输入不能改变表名或列名 → Task 3 注册表 + Task 10 注入用例（含排序键）
- statement timeout 生效 → Task 10 直接查会话设置的用例
- 所有查询强制商家过滤 → Task 5/6/10 的隔离用例
- 180 天与 200 行限制生效 → Task 4/6/10
- 跨零点的「昨天」按 `Asia/Shanghai` 归属，冻结时钟测试通过 → Task 4
- `return_rate` 按区间重算而非日均 → Task 5
- 「最近 30 天退货量趋势」返回退货数据且不与退款混淆 → Task 5
- 退货明细可查询、跨商家不可见 → Task 6
- 多商家同日期数据不串用 → Task 10
- SQL 注入测试通过 → Task 10
- 稳定列顺序与中文标签 → Task 6

- [ ] **Step 4: 更新文档**

- `docs/backend-development-plan.md` §B4 的任务清单勾选，并补一节「实现说明」，记录：指标口径表（本计划开头那张）、`return_rate` 的归属选择与理由、`business_date` 为什么是物理列。
- `docs/project-progress.md` 的「当前阶段」「已完成」「最近验证」「下一步」。

- [ ] **Step 5: 全量门禁 + 前端联动检查**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
cd ../frontend && npm run lint && npm run format:check && npm run typecheck && npm run test && npm run fixtures:check && npm run codegen:check && npx playwright test
```

---

## 本阶段明确不做

- **CSV 导出落文件**属 B6。Task 7 只产出 `ExportSpec` 描述，`/api/exports/{id}` 端点与签名 URL 不在本阶段；DETAIL 回答里的 `export` 字段仍是占位，B6 接管时替换。
- **回答正文、图表与建议**属 B5。Task 9 只把数据、总数、截断和查询计划填进响应，`answer` 文案仍是模板句。
- **Reviewer 与 `quality_attempts`** 属 B5，本阶段 `quality_status` 保持 `NOT_RUN`。
- **`IDENTITY` 模式的商家资料查询**不在 §B4 的任务清单内（第一批明细只有五张经营表），保持 B3 的可见降级；若 B5 需要，届时单独加。
- **真实 DeepSeek 调用**（R3）。
- **订单明细不展开到订单项行**。计划 §B4 把订单明细写作「orders + order_items」，本阶段的
  `DETAIL_SPECS["orders"]` 只返回订单级列（日期、订单号、状态、实付金额、下单时间）。理由是
  一张表格里混着订单级和行项级字段会让「共 N 条」的含义变得含糊——是 N 个订单还是 N 个商品行。
  按商品看订单的诉求由 `按商品查看订单明细`（`orders` + `product` 维度）满足。若 B5 的回答层
  确实需要行项明细，届时新增一个 `order_items` 的 `DetailSpec`，不改这一个。
