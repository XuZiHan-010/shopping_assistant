# N1 数据迁移与确定性演示种子实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程使用可丢弃测试数据，不调用 LLM，无费用。

**目标：** 按 PRD §8.1 完成 v2 状态机所需的表扩展与新表创建，并把演示种子扩展到
能完整演示 S1–S4 四条主场景。

**架构：** **表扩展 + 确定性种子**（Q36），不重建数据模型。现有六张业务表
（`products` / `orders` / `order_items` / `refunds` / `returns` / `support_tickets`）
原地扩列；事件账本、售后主记录、草稿、记忆、简报、幂等记录是新表。迁移分批提交，每批可独立升降级。
**既有行的回填与回滚验证是每批迁移的一部分**：线上演示库已有 v1 订单，
只在空库上能跑通的迁移不算完成（PRD §8.1、§8.2；2026-09-21 N1 计划审查补全）。

**技术栈：** PostgreSQL、SQLAlchemy 2、Alembic、pytest。

**规格来源：**
- `docs/PRD.md` §8.1（表结构变更方向）、§8.2（迁移安全）、§8.3（演示数据确定性）、
  §7.1–§7.4（订单/售后/草稿/库存状态机不变量）
- `docs/deployment.md`（三家固定演示商家、`DEMO_ANALYTICS_SEED_BASE`）
- `AGENTS.md` R5（租户隔离）

---

## 全局约束

- 中文（R1）；标识符英文。
- **不执行任何 Git 操作**（R2）。**不调用 LLM**（R3）。
- **只在可丢弃的本地测试库上操作。** `scripts/seed_demo_data.py` 已有
  `assert_local_database_url()` 守卫，新脚本必须沿用同一守卫。
- **演示商家恒为 3 家**（`docs/deployment.md`：商家 UUID 集合必须与三个固定演示商家
  **精确相等**，多一个少一个都拒绝）。不得因为"方便测试"增减——
  跨商家隔离反例依赖第二家和第三家的存在。
- 金额列一律沿用 `_MONEY = Numeric(14, 2)` 的 `Decimal` 元；
  整数分只在 API 边界出现（契约计划裁定 A5）。
- **随机种子常量只有一处来源**：`app/analytics/demo_data.py` 的
  `DEMO_ANALYTICS_SEED_BASE = 20260804`，第 i 个商家用 `BASE + i`。
  `scripts/seed_demo_data.py` 的 `--random-seed 20260730` **只作用于商家表**，
  两者不可混用——`docs/project-progress.md` 明确记过「别拿错常量」。
- **约束测试必须证明是数据库拦下的**：
  - 一律用 SQLAlchemy 表达式或 `text()`，**不得把原始 SQL 字符串直接传给 `execute()`**。
    SQLAlchemy 2 会在接触数据库之前就抛 `ArgumentError`，`pytest.raises(Exception)` 因此恒绿；
  - **不得使用 `pytest.raises(Exception)`**。捕获 `sqlalchemy.exc.DBAPIError`，再用
    `assert_sqlstate()` 断言 SQLSTATE，CHECK 与 UNIQUE 还要断言约束名；
  - 同一测试里有多条预期失败的语句时，每条都放在 `async with db.begin_nested():` 里。
    否则第一条失败后事务已中止，后续语句会统一报 `25P02`，断言可能因为错误的原因通过。

```python
# backend/tests/integration/_db_asserts.py
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"
NOT_NULL_VIOLATION = "23502"
GENERATED_ALWAYS = "428C9"
RAISE_EXCEPTION = "P0001"      # 触发器 RAISE EXCEPTION


def assert_sqlstate(exc_info, sqlstate: str, constraint: str | None = None) -> None:
    orig = exc_info.value.orig
    assert orig.sqlstate == sqlstate, (orig.sqlstate, str(orig))
    if constraint is not None:
        assert orig.diag.constraint_name == constraint
```

---

## 迁移分批

**一次迁移只做一件事**，每批独立可升降级。批次顺序不可交换（后批依赖前批的列与外键）：

| 批 | 内容 | 依赖 |
| --- | --- | --- |
| M1 | 商品扩列（内容、库存三元组、阈值、版本号） | — |
| M2 | 订单三维投影 + 关闭原因 + 来源标记 + 价格快照，**含既有行回填** | — |
| M3 | 事件账本三张新表（库存、履约、售后），**含既有订单的回填事件**与投影重算任务 | M1、M2 |
| M4 | 草稿与变更账本 | M1 |
| M5 | 优惠券与护栏配置 | M1 |
| M6 | 双端记忆两层 + 顾客信号 + 当日简报 | — |
| M7 | 售后主记录与售后行；`refunds` / `returns` / `support_tickets` 关联列 | M2 |
| M8 | v2 幂等记录表 | — |

`agent_sessions` 与来源状态表**不在本计划**——它们属于
`plans/2026-09-21-n1-session-identity.md` 的 Task 2 与 Task 6，两份计划的表互不重叠。
**表不重叠不等于迁移链不冲突**，两份计划共用下面的规则。

### 迁移链与测试库规则（与会话计划共用）

当前唯一 head 是 `20260831_0016`。N1 的全部新迁移组成**一条线性链**，不分叉，也不用合并节点。

预定顺序与修订号：

| 修订号 | 内容 | 所属 |
| --- | --- | --- |
| `20260921_0017` | `agent_sessions` | 会话计划 Task 2 |
| `20260921_0018` | 来源状态表 | 会话计划 Task 6 |
| `20260921_0019` – `0026` | M1 – M8 | 本计划 Task 1–8 |

实际执行顺序若与上表不同，修订号**按实际创建顺序**取下一个，不预留号段。规则：

1. **创建迁移前**运行 `uv run alembic heads`，必须恰好一个 head，新迁移的 `down_revision` 指向它；
   **创建后**再运行一次，仍须恰好一个 head。出现两个 head 时，立即改新迁移的 `down_revision`
   接到链尾，不用 `alembic merge`——N1 迁移尚未进入任何共享库，线性化没有代价，合并节点反而会让
   `downgrade -1` 的含义变模糊；
2. **执行过 `upgrade` 的迁移文件不再修改**，要改就新增修订。会话计划 Task 6 因此单独建
   `0018`，不回头改 `0017`；
3. **同一个 `TEST_DATABASE_URL` 上不得有两个执行者同时升降级或跑集成测试**。并行开发时每个执行者
   使用自己的测试库，库名仍须通过 `assert_test_database()` 守卫；
4. `tests/integration/test_migrations.py` 增加守卫：

```python
def test_alembic_has_single_head() -> None:
    script = ScriptDirectory.from_config(alembic_config(DEFAULT_TEST_DATABASE_URL))
    assert len(script.get_heads()) == 1, script.get_heads()
```

---

## 文件结构

| 文件 | 责任 | 操作 |
| --- | --- | --- |
| `backend/app/models/analytics.py` | 六张既有表扩列 | 修改 |
| `backend/app/models/events.py` | 库存 / 履约 / 售后事件账本 | 新建 |
| `backend/app/models/after_sales.py` | 售后主记录与售后行 | 新建 |
| `backend/app/models/drafts.py` | 草稿与变更账本 | 新建 |
| `backend/app/models/promotion.py` | 优惠券与护栏配置 | 新建 |
| `backend/app/models/memory_v2.py` | 双端记忆两层、顾客信号、当日简报 | 新建 |
| `backend/app/models/idempotency.py` | v2 幂等记录 | 新建 |
| `backend/app/domain/order_status_mapping.py` | 旧 `order_status` 与三维投影的双向映射（唯一来源） | 新建 |
| `backend/app/jobs/rebuild_projections.py` | 由事件重算并校验订单投影 | 新建 |
| `backend/migrations/versions/*` | M1–M8 八个迁移 | 新建 |
| `backend/app/analytics/demo_data.py` | 扩展确定性数据集 | 修改 |
| `backend/scripts/seed_demo_scenarios.py` | S1–S4 场景种子 | 新建 |
| `backend/tests/integration/_db_asserts.py` | `assert_sqlstate()` 与 SQLSTATE 常量 | 新建 |
| `backend/tests/integration/test_migrations.py` | 约束、单 head 与升降级 | 修改 |
| `backend/tests/integration/test_legacy_backfill.py` | 既有行回填与回滚往返 | 新建 |
| `backend/tests/integration/test_demo_determinism.py` | 种子可复现 | 新建 |
| `docs/database.md` | 表清单同步 | 修改 |

---

### Task 1：M1 商品扩列

**文件：** 修改 `backend/app/models/analytics.py` 的 `Product`；新建迁移。

新增列：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `short_description` | `String(200)` NULL | 卖点 |
| `detail_description` | `Text` NULL | 详细描述 |
| `attributes` | `JSONB` NOT NULL DEFAULT `'{}'` | 开放式属性表，**每项带来源** |
| `image_url` | `String(512)` NULL | 受控地址（D11⑤） |
| `stock_on_hand` | `Integer` NOT NULL DEFAULT 0 | 在库量 |
| `stock_reserved` | `Integer` NOT NULL DEFAULT 0 | 占用量 |
| `low_stock_threshold` | `Integer` NULL | 缺省取全店默认 |
| `content_version` | `Integer` NOT NULL DEFAULT 1 | 审批时的目标版本校验用 |
| `source_locale` | `String(8)` NOT NULL DEFAULT `'zh-CN'` | 源语言（D11⑥） |

### 关键：可售量不建列

**`stock_available` 是派生值（在库 − 占用），不得建列**（PRD §7.4、D5）。
建了列就有了第二事实源，两处更新迟早分叉。查询时现算，或用生成列：

```sql
ALTER TABLE products ADD COLUMN stock_available integer
  GENERATED ALWAYS AS (stock_on_hand - stock_reserved) STORED;
```

生成列是安全的——它由数据库保证一致，应用无法单独写入。**如果用生成列，
必须同时验证它确实不可写**（见步骤 3）。

约束：

```sql
CHECK (stock_on_hand >= 0)
CHECK (stock_reserved >= 0)
CHECK (stock_reserved <= stock_on_hand)   -- 占用不得超过在库
CHECK (content_version >= 1)
```

第三条是**禁止超卖的数据库底线**（PRD §7.4 不变量 1）。应用层的条件更新可能被绕过，
CHECK 不会。

- [x] **步骤 1：改 ORM + 写迁移**
- [x] **步骤 2：验证升降级**

```powershell
cd backend
uv run alembic upgrade head; uv run alembic downgrade -1; uv run alembic upgrade head
uv run alembic check
```

- [x] **步骤 3：验证约束真的拦得住**

在 `tests/integration/test_migrations.py` 追加：

```python
async def test_reserved_cannot_exceed_on_hand(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_product(stock_on_hand=5, stock_reserved=6))
    assert_sqlstate(e, CHECK_VIOLATION, "ck_products_reserved_le_on_hand")


async def test_stock_available_is_not_writable(db) -> None:
    """派生值不得成为第二事实源。"""
    await db.execute(insert_product(stock_on_hand=5))
    with pytest.raises(DBAPIError) as e:
        await db.execute(update(Product).values(stock_available=99))
    assert_sqlstate(e, GENERATED_ALWAYS)


async def test_negative_stock_rejected(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_product(stock_on_hand=-1))
    assert_sqlstate(e, CHECK_VIOLATION, "ck_products_stock_on_hand_nonneg")
```

> 若 ORM 没有把生成列映射成可赋值属性，第二条改用
> `text("UPDATE products SET stock_available = 99")`，断言不变。

**这三条必须在真实 PostgreSQL 上跑**（`REQUIRE_INTEGRATION_DB=1`）。
CHECK 约束在 SQLite 或 Fake 仓储上不生效，绿灯毫无意义——
`docs/project-progress.md` 记过这类教训。

既有商品回填：新增库存列默认 0，既有行即"在库 0、占用 0"，与空的库存账本一致，
不需要补写库存事件。可售库存由 Task 9 的种子连同"期初入库"事件一起写入。

---

### Task 2：M2 订单三维投影与价格快照

**文件：** 修改 `Order` 与 `OrderItem`；新建 `backend/app/domain/order_status_mapping.py`；新建迁移。

`Order` 新增：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `payment_status` | `String(16)` NOT NULL | `PENDING` / `PAID` / `CLOSED` |
| `fulfillment_status` | `String(24)` NOT NULL | 五状态（PRD §7.1） |
| `after_sale_status` | `String(16)` NOT NULL DEFAULT `'NONE'` | 售后维度 |
| `close_reason` | `String(16)` NULL | `TIMEOUT` / `CUSTOMER_CANCEL`；仅 `CLOSED` 时非空 |
| `lifecycle_origin` | `String(16)` NOT NULL | `LEGACY_V1` / `V2` |
| `source_timezone` | `String(64)` NOT NULL DEFAULT `'Asia/Shanghai'` | D14⑩ |

`buyer_key` 已有，不动。**`orders` 上不加 `client_request_id`**：v2 幂等的唯一域是
`role + 主体摘要 + merchant_id + 操作 + client_request_id`（契约 §8.7.3），放在 M8 的
`idempotency_records`。在业务表上加 `(merchant_id, client_request_id)` 唯一索引，会让同店两个顾客
碰巧用同一个客户端 ID 时互相误判冲突。

`OrderItem` 新增价格快照三列：`unit_price`、`discount_amount`、`line_total`（均 `_MONEY`）。

约束：

```sql
CHECK (payment_status IN ('PENDING','PAID','CLOSED'))
CHECK (fulfillment_status IN ('NOT_SHIPPED','SHIPPED','IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED'))
CHECK (payment_status <> 'PENDING' OR fulfillment_status = 'NOT_SHIPPED')  -- 未支付不得已出库
CHECK ((payment_status = 'CLOSED') = (close_reason IS NOT NULL))
CHECK (lifecycle_origin IN ('LEGACY_V1','V2'))
-- 旧状态列必须与投影一致（下表的全部合法组合）
CHECK ((order_status, payment_status, fulfillment_status, COALESCE(close_reason,'')) IN (...))
-- order_items
CHECK (discount_amount >= 0 AND line_total >= 0)
CHECK (line_total = unit_price * quantity - discount_amount)
CHECK (item_amount = line_total)
```

第三条把 PRD §7.1 不变量 2「未支付直接出库属非法迁移」落到数据库。

### 旧 `order_status` 的去留

`order_status` **保留**：v1 指标模板、意图白名单和冻结的 LangGraph 基线都按它查询
（`app/metrics/`、`app/intent/whitelist.py`、`app/repositories/analytics.py`）。
它从此是**由投影确定性派生的兼容列**。旧 → 投影用于回填，投影 → 旧用于派生；
旧 → 投影 → 旧恒等（`SHIPPED` 回填为履约 `SHIPPED`）：

| `order_status` | `payment_status` | `fulfillment_status` | `close_reason` |
| --- | --- | --- | --- |
| `CREATED` | `PENDING` | `NOT_SHIPPED` | — |
| `PAID` | `PAID` | `NOT_SHIPPED` | — |
| `SHIPPED` | `PAID` | `SHIPPED` / `IN_TRANSIT` / `OUT_FOR_DELIVERY` | — |
| `COMPLETED` | `PAID` | `DELIVERED` | — |
| `CANCELLED` | `CLOSED` | `NOT_SHIPPED` | `CUSTOMER_CANCEL` |
| `CLOSED` | `CLOSED` | `NOT_SHIPPED` | `TIMEOUT` |

- 映射只在 `app/domain/order_status_mapping.py` 定义一次。v2 写路径改投影时，在同一事务里
  用它写 `order_status`；上面那条组合 CHECK 保证漏写会直接失败，而不是悄悄分叉；
- 关闭原因上表是存储词汇；API 按冻结契约使用 `USER_CANCELLED` / `PAYMENT_TIMEOUT`。
  `close_reason_to_api` / `close_reason_from_api` 显式双向转换（含空值传递、未知值拒绝）；
  ORM / PostgreSQL CHECK / API 的一致性测试通过映射比对，不要求两层字符串相同。
- **迁移不 import 应用代码**（迁移文件必须冻结，应用模块以后会变），因此迁移里用 SQL `CASE`
  写同一张表，再用一条对照测试保证两者一致。`order_items.item_amount` 同理保留，
  由 CHECK 约束与 `line_total` 相等。

### 既有行回填（本批必须完成，不留给以后）

迁移在同一事务里按顺序执行：

1. **预检，不猜。** 发现以下任一情况即 `RAISE` 中止整个迁移，报出行数和最多 10 个订单号：
   - `order_status IN ('PAID','SHIPPED','COMPLETED')` 但 `paid_at IS NULL`；
   - `order_status IN ('CREATED','CANCELLED','CLOSED')` 但 `paid_at IS NOT NULL`；
   - `order_items.quantity <= 0`，或 `ROUND(item_amount / quantity, 2) * quantity <> item_amount`
     （单价无法无损还原）。

   PostgreSQL 的 DDL 在事务内，中止后库停在 M2 之前的修订，不会留下半迁移状态；
2. 新列先以可空方式加入，按上表回填三维投影与 `close_reason`，`after_sale_status = 'NONE'`，
   `lifecycle_origin = 'LEGACY_V1'`；
3. `order_items` 回填：`line_total = item_amount`、`discount_amount = 0`、
   `unit_price = item_amount / quantity`；
4. 再 `SET NOT NULL` 并加 CHECK；最后对 `lifecycle_origin` 执行 `DROP DEFAULT`，
   此后任何插入都必须显式声明来源。

**为什么历史订单标为 `LEGACY_V1`**：v1 演示数据的订单状态、退款、退货是各自随机生成的
（`app/analytics/demo_data.py`），存在"未支付订单挂着已退款"这类在 v2 状态机里不可能出现的组合。
它们是经营分析的事实，不是 v2 交易流程的起点。因此：

- `after_sale_status` 对历史订单一律为 `NONE`——v2 的售后状态只描述 M7 的售后主记录，
  历史退款 / 退货行不补建主记录；
- v2 的顾客订单、支付、取消、售后路由只处理 `lifecycle_origin = 'V2'` 的订单，历史订单对它们而言
  等同于不存在，返回与越权相同的 `403 RESOURCE_FORBIDDEN`（N2 交易计划、N3 售后计划的入口条件）；
- v1 经营分析照常读取全部订单，结果不变。

降级（downgrade）：删除新增的列与约束。`order_status`、`item_amount` 从未被改写，
降级后 v1 数据逐字节还原。

- [x] **步骤 1：写映射模块与对照测试**

```python
def test_legacy_roundtrip_is_identity() -> None:
    for legacy in LEGACY_ORDER_STATUSES:
        assert to_legacy_status(*from_legacy_status(legacy)) == legacy


def test_migration_case_matches_domain_mapping() -> None:
    """迁移里的 SQL CASE 与应用映射必须是同一张表。"""
    assert parse_case_table(M2_MIGRATION_SOURCE) == FROM_LEGACY_TABLE
```

- [x] **步骤 2：改 ORM + 写迁移（含预检与回填）**
- [x] **步骤 3：验证升降级 + `alembic check`**
- [x] **步骤 4：验证约束**

```python
async def test_unpaid_order_cannot_be_shipped(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_order(payment_status="PENDING", fulfillment_status="SHIPPED"))
    assert_sqlstate(e, CHECK_VIOLATION, "ck_orders_unpaid_not_shipped")


async def test_legacy_status_must_match_projection(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_order(order_status="COMPLETED",
                                      payment_status="PAID", fulfillment_status="NOT_SHIPPED"))
    assert_sqlstate(e, CHECK_VIOLATION, "ck_orders_legacy_status_consistent")


async def test_insert_without_origin_is_rejected(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_order(lifecycle_origin=OMIT))
    assert_sqlstate(e, NOT_NULL_VIOLATION)
```

- [x] **步骤 5：既有行回填与回滚往返**（新建 `tests/integration/test_legacy_backfill.py`）

```python
async def test_backfill_roundtrip_preserves_v1_rows(alembic_at) -> None:
    await alembic_at.downgrade_to(PRE_M2)
    await insert_v1_orders_all_six_statuses_with_items_and_refunds()
    before = await checksum_v1_columns()                  # orders / order_items / refunds / returns
    await alembic_at.upgrade_to(M3)
    assert await projections_match_mapping()
    assert (await rebuild_projections(dry_run=True)).mismatches == 0
    await alembic_at.downgrade_to(PRE_M2)
    assert await checksum_v1_columns() == before
    await alembic_at.upgrade_to("head")


async def test_ambiguous_legacy_row_aborts_migration(alembic_at) -> None:
    await alembic_at.downgrade_to(PRE_M2)
    await insert_v1_order(order_status="PAID", paid_at=None)
    with pytest.raises(DBAPIError, match="paid_at") as e:   # 预检用 RAISE EXCEPTION 中止
        await alembic_at.upgrade_to(M2)
    assert_sqlstate(e, RAISE_EXCEPTION)
    assert await alembic_at.current() == PRE_M2        # 没有半迁移状态
    await alembic_at.reset_to_head()
```

这两条会反复升降级，**必须在独占测试库上串行运行**（见迁移链规则第 3 条），
夹具在 `finally` 里把库恢复到 head。第二条同时断言异常来自预检（SQLSTATE 与消息里的字段名）
和库停在 `PRE_M2`——只断言"升级失败"的话，任何无关错误都能让它通过。

### 三维状态是投影不是事实源

PRD §7.1 不变量 1：事件表是事实源，`orders` 上这几列**只是查询投影**，
必须与事件在同一事务内更新，并提供**由事件重算并校验投影**的任务。
重算任务在 Task 3 事件表建好后一并提供。

---

### Task 3：M3 事件账本三表

**文件：** 新建 `backend/app/models/events.py`、`backend/app/jobs/rebuild_projections.py` 与迁移。

三张表结构一致（**追加写，永不 UPDATE**）：

| 表 | 用途 |
| --- | --- |
| `inventory_events` | 期初入库、订单占用、支付实扣、超时释放、退货回补、商家补货 |
| `fulfillment_events` | 已下单、已支付、已关闭、已出库、运输中、派送中、已签收 |
| `after_sale_events` | 售后状态迁移 |

公共列：`id`、`merchant_id`、`subject_id`（订单/商品/售后 ID）、`event_type`、
`occurred_at`（timestamptz）、`dedupe_key`（UNIQUE）、`payload`（JSONB）、`created_at`。

### 追加写必须由数据库保证

应用层"我们约定不 UPDATE"是约定，不是保证。加触发器：

```sql
CREATE OR REPLACE FUNCTION forbid_event_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% 是追加写事件账本，不允许 UPDATE / DELETE', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_inventory_events_append_only
BEFORE UPDATE OR DELETE ON inventory_events
FOR EACH ROW EXECUTE FUNCTION forbid_event_mutation();
```

三张表各一个触发器。**理由同会话表的角色触发器**：事件账本是重算投影的唯一依据，
一旦被改，所有由它派生的状态都失去可信性，而这种破坏通常在很久以后才被发现。

`dedupe_key` UNIQUE 落实 PRD §7.1 不变量 3（事件写入幂等）。

### 既有订单的回填事件

M2 之后历史订单有投影、没有事件，重算任务无从校验。本迁移为每个历史订单补写履约事件，
使"投影可由事件重算"对全部行成立：

| 旧状态 | 补写的事件（`occurred_at`） |
| --- | --- |
| 全部 | `ORDER_PLACED`（`placed_at`） |
| `PAID` / `SHIPPED` / `COMPLETED` | `PAYMENT_CONFIRMED`（`paid_at`） |
| `SHIPPED` / `COMPLETED` | `SHIPPED`（`paid_at + 6h`，推定） |
| `COMPLETED` | `DELIVERED`（`paid_at + 3d`，推定） |
| `CANCELLED` / `CLOSED` | `ORDER_CLOSED`（`placed_at + 30min`，推定；`payload.close_reason` 按映射） |

- `dedupe_key = 'legacy:{order_id}:{event_type}'`，保证确定性、可重复；
- `payload` 一律带 `{"origin": "LEGACY_V1_BACKFILL"}`；推定时间另加 `"time_inferred": true`。
  **推定时间只用于重算，不作为履约时效的事实**，看板与评测按这个标记排除；
- 不补写库存事件与售后事件：历史商品库存为 0，与空账本一致；历史退款 / 退货不属于 v2 售后
  （见 Task 2）；
- 降级时连表删除，回填事件随之消失，M2 的投影仍在，不影响 v1。

### 重算任务

`rebuild_projections` 从 `fulfillment_events` 与 `after_sale_events` 重算 `payment_status`、
`fulfillment_status`、`close_reason`、`after_sale_status`，再用映射模块推出 `order_status`，
逐列比对。不一致时**报告而不自动改写**——自动改写会掩盖产生分叉的 bug。

- [x] **步骤 1：建表 + 触发器 + 回填事件 + 迁移**
- [x] **步骤 2：写投影重算任务**
- [x] **步骤 3：验证**

```python
async def test_events_are_append_only(db) -> None:
    await db.execute(insert_event(dedupe_key="k1"))
    async with db.begin_nested():
        with pytest.raises(DBAPIError) as e:
            await db.execute(update(InventoryEvent).values(event_type="X"))
        assert_sqlstate(e, RAISE_EXCEPTION)
    async with db.begin_nested():
        with pytest.raises(DBAPIError) as e:
            await db.execute(delete(InventoryEvent))
        assert_sqlstate(e, RAISE_EXCEPTION)


async def test_duplicate_dedupe_key_is_rejected(db) -> None:
    await db.execute(insert_event(dedupe_key="k1"))
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_event(dedupe_key="k1"))
    assert_sqlstate(e, UNIQUE_VIOLATION, "uq_inventory_events_dedupe_key")


async def test_projection_rebuild_detects_drift(db) -> None:
    """投影被手工改坏时，重算任务必须报出来而不是静默修复。"""
    await seed_order_with_events(db, payment="PAID")
    await db.execute(update(Order).values(payment_status="PENDING", order_status="CREATED"))
    report = await rebuild_projections(db, dry_run=True)
    assert report.mismatches == 1


async def test_backfilled_legacy_orders_rebuild_cleanly(db) -> None:
    await seed_v1_orders_via_legacy_generator(db)
    assert (await rebuild_projections(db, dry_run=True)).mismatches == 0
```

---

### Task 4：M4 草稿与变更账本

**文件：** 新建 `backend/app/models/drafts.py` 与迁移。

`drafts` 列：`id`、`merchant_id`、`kind`、`target_type`、`target_id`、
`target_version`（应用时校验）、`draft_version`（批准绑定它）、`state`、
`payload`（JSONB）、`guardrail_snapshot`（JSONB）、`created_by`、
`created_at`、`expires_at`。

`change_ledger` 列：`id`、`merchant_id`、`draft_id`、`drafted_by`、`approved_by`、
`approved_at`、`guardrail_results`（JSONB）、`result`、`created_at`。

约束：

```sql
CHECK (state IN ('STAGED','APPLIED','DISCARDED','EXPIRED'))
CHECK (draft_version >= 1)
```

**枚举里没有 `APPROVED`**（PRD §7.3 不变量 1）——批准不是可复用的持久状态，
只是 apply 事务的入参。数据库层把它挡死，比只写在文档里可靠。

- [x] **步骤 1：建表 + 迁移**
- [x] **步骤 2：验证**

```python
async def test_approved_is_not_a_valid_draft_state(db) -> None:
    """PRD §7.3 不变量 1。"""
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_draft(state="APPROVED"))
    assert_sqlstate(e, CHECK_VIOLATION, "ck_drafts_state")


async def test_terminal_states_cannot_return_to_staged(db) -> None:
    draft_id = await insert_draft_returning_id(db, state="APPLIED")
    # 迁移守卫：已应用不得回到暂存
    with pytest.raises(DBAPIError) as e:
        await db.execute(update(Draft).where(Draft.id == draft_id).values(state="STAGED"))
    assert_sqlstate(e, RAISE_EXCEPTION)
```

第二条需要一个状态迁移触发器，与事件表的 append-only 触发器同法。

---

### Task 5：M5 优惠券与护栏配置

**文件：** 新建 `backend/app/models/promotion.py` 与迁移。

`coupons`：`id`、`merchant_id`、`kind`（`FULL_REDUCTION` / `DISCOUNT`）、
`threshold_amount`、`discount_amount`、`discount_rate`、`scope`（全店/限商品）、
`product_ids`（JSONB）、`starts_at`、`ends_at`（**NOT NULL**）、`state`、`created_at`。

`guardrail_configs`：`merchant_id`、`max_discount_rate`（默认 `0.20`）、
`max_price_change_rate`、`min_allowed_price`（NULL 表示未配置）、`updated_at`、`updated_by`。

约束：

```sql
CHECK (kind IN ('FULL_REDUCTION','DISCOUNT'))
CHECK (ends_at > starts_at)          -- 促销必须有结束日期（D4）
CHECK (max_discount_rate <= 0.20)    -- 最大优惠幅度 20%（Q6）
```

`min_allowed_price` 允许为 NULL，但**为 NULL 时调价草稿一律阻止应用**
（M6：无成本价时不得声称"未低于成本"）。这条是应用层逻辑，在草稿审批任务实现；
本任务只保证列存在且可为空。

- [x] **步骤 1：建表 + 迁移**
- [x] **步骤 2：验证 `ends_at > starts_at` 与 20% 上限两条 CHECK 生效**

---

### Task 6：M6 记忆两层、顾客信号、当日简报

**文件：** 新建 `backend/app/models/memory_v2.py` 与迁移。

| 表 | 关键列 | 隔离键 |
| --- | --- | --- |
| `customer_memories` | `key`、`value`、`category`、`last_confirmed_at` | `merchant_id` + `buyer_key` |
| `merchant_memory_facts` | `content`、`source_ref`、`category` | `merchant_id` |
| `merchant_memory_summaries` | `content`、`category`、`rebuilt_at` | `merchant_id` |
| `customer_signals` | `kind`、`derived_from`、`is_ignored`、`ignore_reason` | `merchant_id` |
| `daily_briefs` | `business_date`、`brief_version`、`payload`、`generated_at` | `merchant_id` |

约束：

```sql
-- 顾客记忆必须双键隔离：merchant_id 与 buyer_key 两列都 NOT NULL
-- 同一商家同一营业日只有一份当前简报（D18⑥）
UNIQUE (merchant_id, business_date)
-- 事实层必须带来源（M11）：source_ref 列 NOT NULL
```

`customer_signals.kind` 取值与契约 `CustomerSignalKind` 逐字一致，含 2026-09-21 补入的 `CONTENT_GAP`（E8）；
`derived_from` 的每项与 `SignalSourceRef` 同形（`source_type: AFTER_SALE / PRODUCT`，`PRODUCT` 带 `content_version`），
**不保存顾客对话标识或提问原文**。S2 种子的内容缺口信号按此形状写入（§9 种子表）。

- [x] **步骤 1：建表 + 迁移**
- [x] **步骤 2：验证**

```python
async def test_customer_memory_requires_both_isolation_keys(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_customer_memory(buyer_key=None))
    assert_sqlstate(e, NOT_NULL_VIOLATION)


async def test_one_current_brief_per_merchant_per_day(db) -> None:
    await db.execute(insert_brief(merchant_id=M1, business_date=D))
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_brief(merchant_id=M1, business_date=D))
    assert_sqlstate(e, UNIQUE_VIOLATION, "uq_daily_briefs_merchant_date")


async def test_merchant_fact_requires_source(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_fact(source_ref=None))
    assert_sqlstate(e, NOT_NULL_VIOLATION)
```

---

### Task 7：M7 售后主记录与既有售后表关联

**文件：** 新建 `backend/app/models/after_sales.py` 与迁移；修改 `Refund`、`ReturnRecord`、`SupportTicket`。

PRD §8.1 与契约 §8.11 的 `after_sale_id` 需要一个承载 §7.2 状态机的主体。既有 `refunds` /
`returns` 按订单行记录**资金**和**货品**动作，二者可以单独发生（`app/models/analytics.py` 顶部注释），
都不适合当状态机主体；工单则是"处理入口"而不是事项本身（PRD §7.2 不变量 4）。所以新增主记录，
其余三张表挂在它下面：

| 表 | 关键列 |
| --- | --- |
| `after_sales` | `id`、`merchant_id`、`buyer_key`、`order_id`（FK）、`after_sale_type`、`state`、`reason`、`refund_amount`（`_MONEY`，后端计算）、`state_version`、`created_at`、`updated_at` |
| `after_sale_lines` | `id`、`after_sale_id`（FK）、`order_item_id`（FK）、`quantity`、`refund_amount`（`_MONEY`） |
| `refunds` / `returns` | 新增 `after_sale_id` UUID NULL FK |
| `support_tickets` | 新增 `after_sale_id` UUID NULL FK，**UNIQUE**（一事项一工单） |

约束：

```sql
CHECK (after_sale_type IN ('RETURN_REFUND','REFUND_ONLY','TICKET'))
CHECK (state IN ('PENDING_MERCHANT','APPROVED','REJECTED','AWAITING_RETURN',
                 'RECEIVED','REFUNDED','AWAITING_CUSTOMER_INFO','CLOSED'))
CHECK (refund_amount >= 0)                       -- after_sales 与 after_sale_lines 各一条
CHECK (quantity > 0)
UNIQUE (after_sale_id, order_item_id)            -- after_sale_lines
UNIQUE (after_sale_id)                           -- support_tickets，允许多个 NULL
```

- 枚举取值与契约 §8.11 的 `AfterSaleState` / `AfterSaleType` **逐字一致**；契约改了，这里同步改；
- **单行累计退款不超过快照金额**（PRD §7.2 不变量 2）跨多行，CHECK 表达不了。数据库层只保证
  单条非负；累计上限由 N3 售后任务在事务内锁定订单行后校验，并在那里写并发测试；
- 状态迁移的合法性由 N3 按契约迁移表实现；本批不加状态迁移触发器，避免同一规则在两处各写一遍；
- 既有 `refunds` / `returns` / `support_tickets` 行的 `after_sale_id` 保持 NULL（历史数据不属于
  v2 售后，见 Task 2），**不需要回填**；降级时删除新列与新表，既有行不受影响。

- [x] **步骤 1：建表、加列 + 迁移**
- [x] **步骤 2：验证**

```python
async def test_after_sale_state_enum_matches_contract(db) -> None:
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_after_sale(state="APPROVED_AND_REFUNDED"))
    assert_sqlstate(e, CHECK_VIOLATION, "ck_after_sales_state")


def test_db_enums_equal_contract_enums() -> None:
    assert parse_check_values(AfterSale, "ck_after_sales_state") == {s.value for s in AfterSaleState}
    assert parse_check_values(AfterSale, "ck_after_sales_type") == {t.value for t in AfterSaleType}


async def test_one_ticket_per_after_sale(db) -> None:
    sid = await insert_after_sale_returning_id(db)
    await db.execute(insert_ticket(after_sale_id=sid))
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_ticket(after_sale_id=sid))
    assert_sqlstate(e, UNIQUE_VIOLATION, "uq_support_tickets_after_sale_id")


async def test_legacy_rows_keep_null_after_sale_link(db) -> None:
    await seed_v1_orders_via_legacy_generator(db)
    assert await count_where(db, Refund.after_sale_id.is_not(None)) == 0
```

第二条要求契约计划 Task 5 已产出 `AfterSaleState` / `AfterSaleType`；若本任务先做，
先以契约 §8.11 的文字为准写 CHECK，契约 Schema 落地后再让这条测试转绿。

---

### Task 8：M8 v2 幂等记录表

**文件：** 新建 `backend/app/models/idempotency.py` 与迁移。

契约 §8.7.3 规定 v2 幂等的唯一域是 `role + 主体稳定摘要 + merchant_id + 端点操作 +
client_request_id`，并要求状态、请求摘要、终态响应与业务写入同一事务。本批只建承载表，
读写服务由 N2 起各写路由实现。

`idempotency_records` 列：`id`、`role`、`principal_digest`（`String(64)`）、`merchant_id`、
`operation`（`String(64)`，如 `shop.orders.create`）、`client_request_id`（`String(128)`）、
`request_digest`（`String(64)`，只取规范化业务输入，排除确认证据）、`status`、
`response_status`、`response_body`（JSONB）、`created_at`、`updated_at`。

```sql
UNIQUE (role, principal_digest, merchant_id, operation, client_request_id)
CHECK (role IN ('CUSTOMER','MERCHANT'))
CHECK (status IN (...))          -- 取值沿用后端计划 §8.5 的处理状态，不另造
```

- `principal_digest` 与会话计划 Task 6 的"稳定主体摘要"**用同一个函数**：访客取
  `session_record_id` 的摘要，已绑定顾客与商家取稳定主体摘要，**不保存明文 `buyer_key`**；
- 不做过期清理：清理属于 N5 运维的 Cron，本批不预设保留期。

- [x] **步骤 1：建表 + 迁移**
- [x] **步骤 2：验证唯一域**

```python
async def test_two_customers_may_reuse_same_client_request_id(db) -> None:
    """契约 §8.7.3：同店两个顾客用同一客户端 ID 不得互相冲突。"""
    await db.execute(insert_idem(role="CUSTOMER", principal_digest="p1", merchant_id=M1,
                                 operation="shop.orders.create", client_request_id="r1"))
    await db.execute(insert_idem(role="CUSTOMER", principal_digest="p2", merchant_id=M1,
                                 operation="shop.orders.create", client_request_id="r1"))


async def test_same_principal_same_operation_conflicts(db) -> None:
    kw = dict(role="CUSTOMER", principal_digest="p1", merchant_id=M1,
              operation="shop.orders.create", client_request_id="r1")
    await db.execute(insert_idem(**kw))
    with pytest.raises(DBAPIError) as e:
        await db.execute(insert_idem(**kw))
    assert_sqlstate(e, UNIQUE_VIOLATION, "uq_idempotency_records_domain")


async def test_same_id_on_different_operation_does_not_conflict(db) -> None:
    base = dict(role="CUSTOMER", principal_digest="p1", merchant_id=M1, client_request_id="r1")
    await db.execute(insert_idem(**base, operation="shop.orders.create"))
    await db.execute(insert_idem(**base, operation="shop.orders.pay"))
```

---

### Task 9：确定性演示种子

**文件：**
- 修改：`backend/app/analytics/demo_data.py`
- 创建：`backend/scripts/seed_demo_scenarios.py`
- 创建：`backend/tests/integration/test_demo_determinism.py`

### 必须能演示的样本（D11⑦、§8.3）

商品目录里必须包含**可复现**的四类：

| 类型 | 用途 |
| --- | --- |
| 完整商品 | 正常导购路径 |
| **缺关键属性** | S2 信息缺口闭环的起点 |
| 描述过短 | 完整度规则命中 |
| 无图片 | 完整度规则命中 |

并且**至少一条商品能完整演示 S2**：顾客提问 → 发现缺口 → 商家补充 → 顾客端可回答。

### 履约事件时间确定性生成（D14②）

```text
支付后 6 小时  → 已出库
次日           → 运输中
第 3 天        → 已签收
```

全部由 `_utc_moment()` 从营业日推算，**不得用 `datetime.now()`**——
用了当前时间，同一种子在不同日期跑出的数据就不同，可复现性立刻失效。

### 场景种子

`seed_demo_scenarios.py` 为 S1–S4 各准备一组数据：

| 场景 | 需要的状态 |
| --- | --- |
| S1 售前成单 | 有货商品 + 已生效券 + 空购物车 |
| S2 信息缺口 | 缺 `产地` 属性的商品 + 对应内容缺口信号 |
| S3 库存告警 | 可售量 3 且近 30 天销量高的商品 + 待批准补货草稿 |
| S4 售后闭环 | 已签收订单 + 完整价格快照 + 在时效内 |

- [x] **步骤 1：写确定性测试**

```python
def test_same_seed_produces_identical_dataset() -> None:
    """同种子两次生成必须逐字节相同。"""
    a = build_demo_dataset(merchant_id=M1, seed=DEMO_ANALYTICS_SEED_BASE + 0, days=30)
    b = build_demo_dataset(merchant_id=M1, seed=DEMO_ANALYTICS_SEED_BASE + 0, days=30)
    assert a == b


def test_different_merchants_get_different_data() -> None:
    a = build_demo_dataset(merchant_id=M1, seed=DEMO_ANALYTICS_SEED_BASE + 0, days=30)
    b = build_demo_dataset(merchant_id=M2, seed=DEMO_ANALYTICS_SEED_BASE + 1, days=30)
    assert a != b


def test_no_wall_clock_in_generation() -> None:
    """生成逻辑不得依赖当前时间。"""
    import app.analytics.demo_data as m
    src = Path(m.__file__).read_text("utf-8")
    assert "datetime.now" not in src
    assert "date.today" not in src


def test_catalog_contains_all_four_completeness_samples() -> None:
    cat = build_demo_catalog(merchant_id=M1, seed=DEMO_ANALYTICS_SEED_BASE)
    assert any(p["attributes"] and p["image_url"] and len(p["detail_description"]) > 100
               for p in cat)                                   # 完整
    assert any("产地" not in p["attributes"] for p in cat)      # 缺关键属性
    assert any(len(p["detail_description"] or "") < 30 for p in cat)   # 描述过短
    assert any(p["image_url"] is None for p in cat)            # 无图片


def test_fulfillment_times_are_deterministic() -> None:
    ds = build_demo_dataset(merchant_id=M1, seed=DEMO_ANALYTICS_SEED_BASE, days=7)
    paid = find_event(ds, "PAYMENT_CONFIRMED"); shipped = find_event(ds, "SHIPPED")
    assert shipped.occurred_at - paid.occurred_at == timedelta(hours=6)
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过**

- [x] **步骤 3：三家商家完整重灌验证**

```powershell
cd backend
uv run python ../scripts/seed_demo_data.py --dry-run --merchant-count 3
uv run python ../scripts/seed_demo_data.py --seed --merchant-count 3
uv run python -m scripts.seed_demo_analytics --force-full-rebuild
uv run python -m scripts.seed_demo_scenarios --seed
```

期望：dry-run 计划与实际写入一致；商家数恰好 3；`rebuild_projections --dry-run` 零不一致。

命令位置按现状写：商家种子 `seed_demo_data.py` 在**仓库根**的 `scripts/`，不在 `backend/scripts/`，
所以从 `backend` 以相对路径调用，与 `docs/deployment.md` 的恢复步骤一致；
`seed_demo_analytics` 与新建的 `seed_demo_scenarios` 在 `backend/scripts/`，用 `-m` 调用。

### 种子必须与 M2/M3 的新约束一致

- `demo_data.py` 生成的经营订单（`lifecycle_origin = 'LEGACY_V1'`）要同时写三维投影、
  `close_reason` 和与 M3 回填**同规则**的履约事件；否则全量重灌后重算任务会报不一致。
  投影取值调用 `order_status_mapping`，事件规则与迁移回填共用一张表并有对照测试；
- 场景种子写的订单一律 `lifecycle_origin = 'V2'`，事件时间按上文 D14② 生成，**不带**
  `time_inferred`；S4 所需的售后前置状态走 M7 的主记录，不复用历史退款行；
- 每个有库存的商品写一条 `INITIAL_STOCK` 库存事件，使库存账本可重算出 `stock_on_hand`
  （PRD §7.4 不变量 3）；
- 种子不写 `idempotency_records`——幂等记录只由真实写请求产生。

---

### Task 10：自检与文档同步

- [x] **步骤 1：迁移链完整性**

```powershell
cd backend
uv run alembic heads          # 恰好一个 head
uv run alembic upgrade head
uv run alembic downgrade base
uv run alembic upgrade head
uv run alembic check
```

全部通过，且 `heads` 只列出一个修订。**这些命令只能对准本地可丢弃的测试库**，
执行前确认 `DATABASE_URL` 指向的库名能通过 `assert_test_database()`。**`downgrade base` 是关键**——它会暴露"降级脚本没写全"的迁移，
而这种迁移在只测 `-1` 时看不出来。

- [x] **步骤 2：真实数据库全量**

```powershell
cd backend; $env:REQUIRE_INTEGRATION_DB=1; uv run pytest -rs
```

期望：全绿，`-rs` 的 skip 摘要里**没有任何集成测试**。所有 CHECK 与触发器只有在真实
PostgreSQL 上才生效；不设 `REQUIRE_INTEGRATION_DB=1` 时缺库会整批 skip，看起来也是绿的。

> **跑之前先确认测试库是独占的。** `docs/project-progress.md` 记过：
> 并发 `TRUNCATE_ALL_TABLES` 会导致锁竞争与死锁。另外全量 pytest 会清空
> `knowledge_documents` 与经营数据表，跑完需要重新执行
> `backend/scripts/import_wiki.py` 与 `seed_demo_analytics.py`。

- [x] **步骤 3：派生值与第二事实源扫描**

```powershell
cd backend
rg -n "stock_available\s*=" app/ --glob '!*.pyc'
```

期望：**零命中**——可售量只能派生，任何赋值都是第二事实源。

```powershell
rg -n 'pytest\.raises\(Exception\)|execute\(\s*f?"' tests/integration/
```

期望：**零命中**——见全局约束，原始字符串 SQL 与宽泛异常会让约束测试假绿。

- [x] **步骤 4：同步 `docs/database.md`** 的表清单与本轮新增表。

- [x] **步骤 5：更新进度快照**，记录迁移批次、通过的约束测试数、
  回填往返测试结果、**未执行 Git 操作**、**未调用 LLM**。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| `agent_sessions` 与来源状态表 | `plans/2026-09-21-n1-session-identity.md` Task 2、Task 6 |
| pgvector 与向量索引表 | N4（A7） |
| 评测运行与结果表 | 评测骨架计划 |
| 任何业务逻辑（占库、退款计算、累计退款上限、草稿应用、幂等读写） | N2 / N3 各路由任务；本计划只建表、约束与回填 |
| 为历史退款 / 退货补建售后主记录 | 不做：历史数据不属于 v2 售后（Task 2） |
| 幂等记录的过期清理 | N5 运维 Cron |
| 生产库迁移 | 发布阶段单独执行（PRD §8.2、Q34），不由 Backend 或 Cron 并发执行 |
