# N2 顾客端交易闭环实施计划（S1）

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程 Fake LLM，零费用。

**目标：** 实现 PRD C1–C5 的最小集后端：店铺与商品浏览、购物车、结账占库、模拟支付、
订单履约事件，并接上顾客导购 Agent 的最小工具集，使**场景 S1 端到端可跑**。

**架构：** 路由层只做鉴权与 Schema；占库、价格计算、状态迁移全部在应用服务层的
**单一事务**内完成。顾客工具注册进 §6.9 的注册表，由 §6.10 的循环驱动。

**技术栈：** FastAPI、SQLAlchemy 2（`SELECT ... FOR UPDATE` / 条件更新）、pytest。

**规格来源：** PRD C1–C5、§7.1、§7.4、S1；融合决策 D5、D12、D13、D14；
后端计划 §8.8、§8.10（字段契约）、§6.9。

---

## 入口条件

- [x] `n2-tool-loop-and-registry` 已完成：注册表、四类闸门、循环可用；
- [x] 契约计划 Task 2（组 1 顾客会话）与 Task 4（组 3 交易）已完成：§8.8、§8.10 字段已定；
- [x] 数据迁移计划 M1、M2、M3、M8 已完成：库存三元组、订单三维投影、事件账本三表、`idempotency_records` 在库；
- [x] 会话计划 Task 7 已完成：3 条顾客会话路由可用，`CartMergePort` 端口在生产装配中注入的是 `EmptyCartMerge`；
- [x] **核对 §8.8 / §8.10 的字段与本计划引用是否一致**，不一致先改计划。

---

## 全局约束

- 中文（R1）；**不执行 Git 操作**（R2）；**不调用真实 LLM**（R3）。
- **金额只由后端计算**：不采信前端提交、不采信模型输出（D13）。
- 所有顾客数据查询**强制 `merchant_id` + `buyer_key` 双重过滤**（D7①）。
- API 金额为整数分，库内 `Decimal` 元，转换规则见契约计划 §8.7.8。
- 每完成一组路由，**同一次变更内**完成 OpenAPI 导出、`codegen`、Adapter 与快照测试
  （契约计划 §8.0.1 五项完成门槛）。

---

## 本计划用到的写策略

§6.9 已用 `WritePolicy` 区分四类写，**顾客购物车不会被误套进商家草稿审批**。本计划的工具
与动作按下表取值，执行者不得自行改动：

| 动作 | 发起方 | `WritePolicy` |
| --- | --- | --- |
| `search_products` / `get_product` / `get_shop_policy` | Agent | `READ_ONLY` |
| `set_cart_item` | Agent 或界面 | `CUSTOMER_DIRECT`（设置绝对数量，天然幂等） |
| 提交订单 / 模拟支付 / 取消 | **仅界面** | 不是工具，走路由 + `client_request_id` |

**顾客 Agent 不得有任何下单或支付工具**（C2「不可以下单或扣款」）。这条比 `WritePolicy`
更严：它不是"写之前要确认"，而是"根本不给模型这个能力"。

- [x] **Task 0：**（2026-09-23 完成；执行期裁定：只拦写策略非 READ_ONLY 的顾客工具，见台账）在 `app/tools/registry.py` 追加自检——`CUSTOMER` 角色工具的名称含
      `order` / `pay` / `checkout`，或 `write_policy=MERCHANT_DRAFT`，均注册失败。补对应单测：

```python
@pytest.mark.parametrize("name", ["submit_order", "pay_order", "checkout"])
def test_customer_agent_cannot_register_order_or_payment_tools(name) -> None:
    with pytest.raises(ToolRegistrationError):
        registry.register(ToolSpec(name=name, roles=frozenset({ToolRole.CUSTOMER}),
                                   write_policy=WritePolicy.CUSTOMER_CONFIRMATION, ...))
```

按名称拦截是兜底而非主防线——主防线是**这些工具根本不被写出来**。
但名称自检能挡住将来有人"顺手"加一个的情况。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `backend/app/api/routes/v2/shop_catalog.py` | 店铺、商品、券（公开） |
| `backend/app/api/routes/v2/shop_cart.py` | 购物车 |
| `backend/app/api/routes/v2/shop_orders.py` | 下单、列表、详情、事件、支付、取消 |
| `backend/app/api/routes/v2/shop_chat.py` | 顾客 Agent，默认 SSE |
| `backend/app/services/v2/checkout.py` | **结账事务**：重算、占库、快照 |
| `backend/app/services/v2/payment.py` | 模拟支付与超时关闭的竞争裁决 |
| `backend/app/services/v2/stock_tier.py` | 库存三档映射 |
| `backend/app/tools/customer/` | `search_products` / `get_product` / `get_shop_policy` / `set_cart_item` |
| `backend/app/jobs/close_expired_orders.py` | 30 分钟未支付关闭（Cron 接线在 N5） |
| `backend/tests/integration/v2/test_checkout_concurrency.py` | **并发与幂等** |
| `backend/tests/e2e/test_s1_presale_to_payment.py` | S1 端到端 |

---

### Task 1：店铺与商品公开浏览（C1）

路径：`GET /stores/{shop_slug}`、`/products`、`/products/{product_id}`、`/coupons`。

### 规则

- `shop_slug` → `merchant_id` 映射**只在服务端**，响应不含 `merchant_id`；
- **库存只返回三档** `stock_band` ∈ `IN_STOCK` / `LOW_STOCK` / `OUT_OF_STOCK`（契约 §8.8.1 `StockBand`；
  原写法 `stock_tier` / `LOW` / `SOLD_OUT` 与契约不一致，2026-09-23 执行期按契约修正），
  **不返回任何数量字段**（D5）；阈值线与商家端库存告警共用 `AlertRules`；
- 券只返回**已生效**的（`starts_at <= now < ends_at` 且未停用）；
- 图片地址只接受演示静态资源或白名单 HTTPS（D11⑤），**后端不抓取**任意 URL。

- [x] **步骤 1：写失败测试**（2026-09-23，Opus；实测见 `tests/api/v2/test_shop_catalog.py` 等，台账见
      `.superpowers/sdd/2026-09-21-n2-trade-closed-loop/progress.md`）

```python
async def test_product_response_never_exposes_stock_quantity(client) -> None:
    body = (await client.get(f"/api/v2/shop/stores/{SLUG}/products/{PID}")).json()
    flat = json.dumps(body)
    for leak in ("stock_on_hand", "stock_reserved", "stock_available", "quantity"):
        assert leak not in flat
    assert body["stock_band"] in {"IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"}


async def test_only_active_coupons_listed(client) -> None:
    ids = {c["id"] for c in (await client.get(f"/api/v2/shop/stores/{SLUG}/coupons")).json()}
    assert EXPIRED_COUPON not in ids and FUTURE_COUPON not in ids and ACTIVE_COUPON in ids


async def test_unknown_slug_indistinguishable_from_disabled_shop(client) -> None:
    a = await client.get("/api/v2/shop/stores/no-such-shop")
    b = await client.get(f"/api/v2/shop/stores/{DISABLED_SLUG}")
    assert a.status_code == b.status_code and a.json() == b.json()
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（门槛 4 Adapter 归模块 F 的 `shop/` 工程，见台账裁定；
      另补端点安全用例 SEC-CATALOG-001–004）

---

### Task 2：购物车（C3）

路径：`GET /cart`、`PUT /cart/items/{product_id}`、`DELETE /cart/items/{product_id}`。

### 规则

- **购物车不占库存**（D13）；加购只校验在售与未售罄；
- `PUT` 设置**绝对数量**，`quantity=0` 等价删除，天然幂等；
- 来源闸门：**Agent 调 `set_cart_item` 时**，商品必须在本对话中由工具返回过；
  顾客在界面直接加购不经过来源闸门（它不是模型行为）。
- **购物车合并（D7⑥）**：实现会话计划定义的 `CartMergePort.merge_guest_into_buyer(...)`，并在生产装配中替换 N1 的
  `EmptyCartMerge`。合并在 `bind_demo_customer` 的同一事务内执行；同一身份重复绑定不重复合并；重新绑定同一演示身份时
  返回该身份已有的购物车（`n2-shop-nextjs-app` 入口条件依赖这一点）。替换后 `EmptyCartMerge` 不得再出现在生产装配中。
  **合并规则按 PRD C3（2026-09-21 裁定，E9）**：同商品数量相加、单行上限 99；剔除已下架或售罄商品；超 50 行按加入时间
  保留最新 50 行；合并后清空访客购物车；不校验库存数量。任一调整发生时绑定响应 `cart_adjusted=true`。

- [x] **步骤 1：写失败测试**（台账：`.superpowers/sdd/2026-09-21-n2-trade-closed-loop/progress.md`）

```python
async def test_cart_does_not_reserve_stock(client, db) -> None:
    before = await stock(db, PID)
    await client.put(f"/api/v2/shop/cart/items/{PID}", json={"quantity": 3}, headers=CUST)
    assert await stock(db, PID) == before


async def test_agent_cannot_add_product_not_seen_in_conversation(loop) -> None:
    """D12②：购物车来源闸门。"""
    out = await loop.run(script=[tool_use("set_cart_item", product_id=UNSEEN_PID)])
    assert out.stop_reason == "FATAL"


async def test_put_is_idempotent(client) -> None:
    for _ in range(3):
        await client.put(f"/api/v2/shop/cart/items/{PID}", json={"quantity": 2}, headers=CUST)
    cart = (await client.get("/api/v2/shop/cart", headers=CUST)).json()
    assert [i["quantity"] for i in cart["items"] if i["product_id"] == PID] == [2]


async def test_bind_merges_guest_cart_once(client) -> None:
    """D7⑥：访客购物车在绑定事务内合并；重复绑定同一身份不重复合并。"""
    await client.put(f"/api/v2/shop/cart/items/{PID}", json={"quantity": 2}, headers=GUEST)
    for _ in range(2):
        r = await client.post("/api/v2/shop/sessions/demo-customer", json={}, headers=GUEST)
        assert r.status_code == 200
    cart = (await client.get("/api/v2/shop/cart", headers=GUEST)).json()
    assert [i["quantity"] for i in cart["items"] if i["product_id"] == PID] == [2]


def test_production_wiring_no_longer_uses_empty_cart_merge() -> None:
    # 实际落地的装配函数是 `app.api.session_deps.get_cart_merge_port()`（不接受参数），
    # 不是本计划最初示例里的 `build_cart_merge_port(settings())`（2026-09-24 Astra 入口-N2 复审核对）。
    assert not isinstance(get_cart_merge_port(), EmptyCartMerge)


async def test_merge_sums_caps_and_drops_with_visible_adjustment(client) -> None:
    """PRD C3 / E9：相加、99 截顶、剔除售罄，调整必须体现在 cart_adjusted。"""
    await set_buyer_cart(BUYER, {PID: 60})
    await client.put(f"/api/v2/shop/cart/items/{PID}", json={"quantity": 50}, headers=GUEST)
    await client.put(f"/api/v2/shop/cart/items/{SOLD_OUT_LATER}", json={"quantity": 1}, headers=GUEST)
    await mark_sold_out(SOLD_OUT_LATER)
    r = await client.post("/api/v2/shop/sessions/demo-customer", json={}, headers=GUEST)
    assert r.json()["cart_adjusted"] is True
    items = {i["product_id"]: i["quantity"] for i in (await client.get("/api/v2/shop/cart", headers=GUEST)).json()["items"]}
    assert items[PID] == 99 and SOLD_OUT_LATER not in items


async def test_clean_merge_reports_no_adjustment(client) -> None:
    await client.put(f"/api/v2/shop/cart/items/{PID}", json={"quantity": 1}, headers=GUEST)
    r = await client.post("/api/v2/shop/sessions/demo-customer", json={}, headers=GUEST)
    assert r.json()["cart_adjusted"] is False
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23；Adapter 门槛同 Task 1 裁定归 `shop/` 工程）

---

### Task 3：结账事务（C4）——本计划的核心

`POST /orders`。**订单创建与占库在同一事务内原子完成**（PRD §7.4 不变量 2）。

### 事务内的固定步骤

```text
BEGIN
  1. 按购物车重新读取商品当前价格、状态、券适用性      ← 不沿用对话旧值（D12③）
  2. 逐行条件更新占库：
       UPDATE products SET stock_reserved = stock_reserved + :q
       WHERE id = :pid AND stock_on_hand - stock_reserved >= :q
     影响行数为 0 → 该行不可用，整单回滚并返回不可用清单
  3. 计算价格快照：先逐行舍入到分，再求和（§8.7.8 舍入顺序）
  4. 插入 orders（PENDING / NOT_SHIPPED）、order_items（含快照）
  5. 追加事件：fulfillment_events「已下单」、inventory_events「订单占用」
COMMIT
```

**第 2 步的条件更新是禁止超卖的应用层防线；数据迁移计划 M1 的
`CHECK (stock_reserved <= stock_on_hand)` 是数据库层底线。两道都要有。**

### 规则

- 不可用项（库存不足、下架、券过期）**明确返回清单，不静默调整**；
- 按契约 §8.7.3 的唯一域幂等（`role + 主体摘要 + merchant_id + 操作 + client_request_id`，
  记录在 M8 的 `idempotency_records`）：同一主体同 ID 重复提交返回原订单；**同店另一顾客用同一 ID
  不受影响**，并为此写一条测试；
- 新订单写 `lifecycle_origin = 'V2'`，投影变更时在同一事务里用 `order_status_mapping` 同步
  `order_status`（数据迁移计划 Task 2）；支付、取消只接受 `V2` 订单，历史 `LEGACY_V1` 订单
  按不存在处理，返回与越权相同的 403；
- `buyer_key` 取自会话，不接受前端传入。
- 关闭原因响应调用 `close_reason_to_api`，API 词汇进入持久化前调用
  `close_reason_from_api`（均在 `app/domain/order_status_mapping.py`）；数据库保留
  `CUSTOMER_CANCEL` / `TIMEOUT`，API 只用 `USER_CANCELLED` / `PAYMENT_TIMEOUT`。

- [x] **步骤 1：写并发与幂等测试**（**必须在真实 PostgreSQL 上跑**）

```python
async def test_last_unit_race_has_exactly_one_winner(db_pool) -> None:
    """PRD §7.4 不变量 1：任何路径都不得产生负可售量。"""
    await set_stock(PID, on_hand=1, reserved=0)
    results = await asyncio.gather(
        *[submit_order(buyer=f"b{i}", pid=PID, qty=1) for i in range(10)],
        return_exceptions=True)
    assert sum(1 for r in results if is_created(r)) == 1
    assert (await stock(PID)).available == 0


async def test_failed_line_rolls_back_whole_order(db) -> None:
    """任一行不可用，整单回滚——不得出现"部分占库"。"""
    await set_stock(PID_A, on_hand=5); await set_stock(PID_B, on_hand=0)
    r = await submit_order(lines=[(PID_A, 1), (PID_B, 1)])
    assert r.status_code == 409
    assert (await stock(PID_A)).reserved == 0
    assert await count(db, "orders") == 0


async def test_duplicate_submission_returns_same_order(client) -> None:
    a = await client.post("/api/v2/shop/orders", json=body(crid="r1"), headers=CUST)
    b = await client.post("/api/v2/shop/orders", json=body(crid="r1"), headers=CUST)
    assert a.json()["id"] == b.json()["id"]
    assert (await stock(PID)).reserved == 1          # 只占一次


async def test_client_supplied_price_is_rejected(client) -> None:
    r = await client.post("/api/v2/shop/orders",
                          json={**body(), "total_cents": 1}, headers=CUST)
    assert r.status_code == 422                      # extra="forbid"


async def test_price_snapshot_survives_later_price_change(client, db) -> None:
    order = (await client.post("/api/v2/shop/orders", json=body(), headers=CUST)).json()
    await set_price(PID, 999_00)
    detail = (await client.get(f"/api/v2/shop/orders/{order['id']}", headers=CUST)).json()
    assert detail["items"][0]["unit_price_cents"] == ORIGINAL_PRICE_CENTS
```

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23；Adapter 门槛同 Task 1 裁定归 `shop/` 工程）

```powershell
cd backend; $env:REQUIRE_INTEGRATION_DB=1
uv run pytest tests/integration/v2/test_checkout_concurrency.py -v
```

并发测试在 Fake 仓储上跑绿**毫无意义**——它测的正是数据库的行锁与条件更新。

---

### Task 4：模拟支付与超时关闭的竞争（C4、§7.1 不变量 4）

`POST /orders/{order_id}/pay`、`POST /orders/{order_id}/cancel`、`close_expired_orders` 任务。

### 竞争裁决

支付与关闭都用**同一个条件更新**抢状态。**支付还必须自己检查 30 分钟截止时间**：

```sql
-- 支付
UPDATE orders SET payment_status = 'PAID'
WHERE id = :oid AND payment_status = 'PENDING'
  AND created_at > :now - interval '30 minutes'

-- 关闭（超时任务或顾客取消）
UPDATE orders SET payment_status = 'CLOSED'
WHERE id = :oid AND payment_status = 'PENDING'
```

**为什么支付要自己查截止时间**：`close_expired_orders` 由 Cron 调度，Railway Cron 的最小间隔
是分钟级且不保证准时（`docs/deployment.md`）。若支付只看 `PENDING`，Cron 还没跑到的
第 33 分钟订单**仍能支付成功**，违反 PRD §7.1"30 分钟未支付关闭"。
**Cron 只负责释放占用（清理），不负责判定超时（正确性）**。
超时后支付返回 `409 ILLEGAL_STATE_TRANSITION`，并在同一事务内顺手完成关闭与释放。

影响行数为 1 者胜；为 0 者返回 `409 ILLEGAL_STATE_TRANSITION`，`details` 只含当前状态。
胜者在同一事务内完成库存动作：

| 胜者 | 库存动作 | 事件 |
| --- | --- | --- |
| 支付 | 占用 −q，在库 −q（占用转实扣） | 履约事件 `PAYMENT_CONFIRMED`；库存事件「支付实扣」 |
| 关闭 | 占用 −q（释放） | 履约事件 `ORDER_CLOSED`（契约 §8.10，PRD §7.1 已含「已关闭」）；库存事件「超时释放」 |

- [x] **步骤 1：写失败测试**（台账：`.superpowers/sdd/2026-09-21-n2-trade-closed-loop/progress.md`）

```python
async def test_pay_and_close_race_has_one_winner(db_pool) -> None:
    oid = await pending_order(qty=2)
    results = await asyncio.gather(pay(oid), close_expired(force=oid), return_exceptions=True)
    status = (await get_order(oid)).payment_status
    assert status in {"PAID", "CLOSED"}
    s = await stock(PID)
    if status == "PAID":
        assert s.reserved == 0 and s.on_hand == INITIAL - 2
    else:
        assert s.reserved == 0 and s.on_hand == INITIAL      # 未被重复释放或误扣


async def test_pay_is_idempotent(client) -> None:
    for _ in range(3):
        await client.post(f"/api/v2/shop/orders/{OID}/pay",
                          json={"client_request_id": "p1"}, headers=CUST)
    assert (await stock(PID)).on_hand == INITIAL - 1         # 只扣一次


async def test_payment_after_deadline_fails_even_if_job_has_not_run(client, clock) -> None:
    """正确性不依赖 Cron 调度精度。"""
    oid = await pending_order(created=clock.now - timedelta(minutes=33))   # 任务尚未跑
    r = await pay(client, oid, now=clock.now)
    assert r.status_code == 409
    assert (await get_order(oid)).payment_status == "CLOSED"
    assert (await stock(PID)).reserved == 0                              # 顺手释放


async def test_close_job_only_touches_orders_older_than_30_minutes(clock) -> None:
    fresh = await pending_order(created=clock.now - timedelta(minutes=29))
    stale = await pending_order(created=clock.now - timedelta(minutes=31))
    await close_expired_orders(now=clock.now)
    assert (await get_order(fresh)).payment_status == "PENDING"
    assert (await get_order(stale)).payment_status == "CLOSED"
```

`close_expired_orders` 接受 `now` 参数而不是内部调 `datetime.now()`——
这是能写出第三条测试的前提，也让 N5 的 Cron 追赶漏跑时行为可预测。

- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23；Adapter 门槛同 Task 1 裁定归 `shop/` 工程）

---

### Task 5：订单列表、详情与履约事件（C5）

`GET /orders`、`/orders/{order_id}`、`/orders/{order_id}/events`。

- 三维状态分列返回（D14⑥）；**详情不内嵌事件数组**，履约事件只由 `/events` 游标分页端点提供
  （契约 §8.10：避免无界响应；投影由事件重算，客户端不得据投影推断事件缺失）；
- 事件时间 UTC 存储，响应带来源时区，展示换算交给前端（D14⑩）；
- 跨顾客、跨店铺访问一律 `403 RESOURCE_FORBIDDEN`，与「不存在」逐字段一致
  （复用会话计划 Task 5 的 `require_owned()`，**不得另写一套判定**）。

- [x] **步骤 1：写失败测试**——含同一 `buyer_key` 在另一家店的订单不可见（跨店双重过滤）。
- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23；Adapter 门槛同 Task 1 裁定归 `shop/` 工程）

---

### Task 6：顾客导购工具与 Chat 路由

工具：`search_products`、`get_product`、`get_shop_policy`（读）；`set_cart_item`（写自有数据）。
路由：`POST /api/v2/shop/chat`，默认 SSE，事件集见契约计划 §8.7.5。

### 规则

- 工具返回的价格与库存档位**来自工具结果**，模型不得自行陈述数字；
- 属性缺失时工具返回「缺失」而不是空字符串，让模型无法把空当成"没有此属性"；
- `tool_call` / `tool_result` 事件只含 `ToolDisplay`，**`payload` 不进 SSE**；
- 知识检索沿用既有 `app/knowledge/retrieval.py`（混合检索在 N4）。

- [x] **步骤 1：写失败测试**——SSE 最后一个事件是 `turn_complete` 或 `error`；
      `tool_result` 事件不含参数、SQL、完整结果行；缺属性时回答不编造。
- [x] **步骤 2：确认失败 → 实现 → 确认通过 → 五项完成门槛**（2026-09-23；Adapter 门槛同 Task 1 裁定归 `shop/` 工程）

---

### Task 7：S1 端到端

**文件：** `tests/e2e/test_s1_presale_to_payment.py`

```text
顾客提问 → Agent 检索本店商品并对比 → 加购 → 结账摘要（展示用）
→ 顾客界面提交订单并占库 → 顾客界面模拟支付 → 订单事件出现「已支付」
```

- [x] **步骤 1：用 `FakeLlmClient` 脚本编排 Agent 的工具调用序列**
- [x] **步骤 2：断言每一步的数据库副作用**：购物车行、占用量、订单三维状态、事件行
- [x] **步骤 3：把本场景登记进 `app/eval/datasets/quality/`**（登记在 `quality/scenarios/`，理由见台账），供后续回归

PRD §12.2 要求 S1–S4 用 Fake LLM 浏览器 E2E。**本任务是后端 E2E**；
浏览器 E2E 在 `n2-shop-nextjs-app` 计划完成后补。

---

### Task 8：自检

- [x] **登记安全集**（SEC-INJECTION-001–007；本计划不是 N2 最后完成的一份——草稿计划 Task 8 仍未完成——`CURRENT_MILESTONE` 未推进，见台账）：`SEC-INJECTION-*` 的**顾客对话入口**（2026-09-22 由工具循环计划移入，打本计划 Task 6 的 `POST /api/v2/shop/chat`）、商品描述入口与知识文档入口用例写入
      `app/eval/datasets/security/`（`introduced_in: N2`、`form: ENDPOINT`，每类 ≥ 3 条；评测计划 Task 2 的路由覆盖守卫会在路由注册后强制要求）。若本计划是 N2 三份（工具循环、交易、草稿）中最后完成的一份，把
      `test_security_gate.py` 的 `CURRENT_MILESTONE` 改为 `"N2"`，并确认七类 ≥ 21 条、零失败、零 skip。
      **顺序约束**：`CURRENT_MILESTONE` 为 `"N1"` 时登记任何 `introduced_in: N2` 用例都会让
      `test_no_case_is_introduced_ahead_of_its_milestone` 失败；若本计划先于草稿计划完成，
      用例文件须与草稿计划 Task 9 的用例、里程碑推进在同一次变更里落地（由 N2 收尾统一执行）。


```powershell
cd backend
rg -n "datetime.now\(\)|date.today\(\)" app/services/v2/ app/jobs/close_expired_orders.py
rg -n "stock_on_hand|stock_reserved" app/api/routes/v2/shop_catalog.py
uv run pytest; uv run ruff check .; uv run mypy app
$env:REQUIRE_INTEGRATION_DB=1; uv run pytest tests/integration/v2/ -v
```

前两条期望零命中（业务逻辑不读墙钟；公开浏览路由不接触库存原值）。

更新 `docs/project-progress.md`：S1 后端 E2E 状态、并发测试结果、未执行 Git、未调用 LLM。

---

## 本计划明确不做的事

| 不做 | 归属 |
| --- | --- |
| 顾客端页面 | `n2-shop-nextjs-app` |
| 演示顾客绑定路由 | 会话计划 Task 7（N1 已落地）；本计划 Task 2 只负责替换真实购物车合并实现 |
| 售后 | `n3-customer-skills-and-after-sales` |
| 5 个 Skill 的完整提示词 | N3；本计划只用最小工具集 |
| 超时关闭的 Cron 接线 | `n5-budget-ops-and-railway` |
