# WS · 顾客端店面重设计 实施计划

> **给执行者：** 用 `superpowers:executing-plans`（或 `superpowers:subagent-driven-development`）逐任务推进，步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程使用 Fake / 脚本化 LLM，零费用。
> **进度只在 `docs/project-progress.md` 维护。**

**目标：** 按 2026-09-28 定稿原型，把 `shop/` 重建成 ACME storefront 式外壳：顶栏视图切换、智能助手首页与对话、右侧常驻购物车、订单视图、动态抽屉、偏好设置。同时补齐支撑它的四项后端能力（热门排序、商品详情缺失属性、订单摘要首件商品与最近更新时间、只读订单工具），并把 24 个演示商品换成真实商品与图片。

**架构：**
- 后端只做**增量**：一个查询参数、三个响应字段、一个只读工具、演示目录内容。不新增路径。
- 字段流向保持 `generated.ts → api/adapters → types → Provider/组件`，组件不直接消费 `generated.ts`。
- 聊天状态从 `AssistantClient` 上移到外壳层的 `ChatProvider`，视图切换不丢对话。
- 公开数据（热门、全部商品、商品详情）仍在服务端渲染；会话数据（购物车、订单、记忆、对话）只在客户端取，会话 ID 只存内存。

**技术栈：** FastAPI、Pydantic v2、SQLAlchemy 2、pytest；Next.js 16（App Router）、React 19、Vitest + Testing Library、Playwright。

**规格：** `docs/specs/2026-09-28-shop-storefront-ui-design.md`（下称“规格”）。视觉参考为定稿原型 `frontend/prototypes/borough-shop-redesign.html`：只参考视觉与交互，不搬它的 DOM 脚本。

**阶段定位：** 新阶段「WS」（Task 1 写入 PRD §15）。
- 后端部分（Task 1–6）可以与商家端 W、N4 后端并行；
- 前端外壳（Task 7 起）必须等 **W Task 5（token 与外壳）** 完成；
- `docs/api.json` 的导出与 W、N4 串行，规则见 §三。

## Global Constraints

- 助手对外名称一律为「智能助手」（英文 `Assistant`）。不得出现“店员”“导购助手”。
- 色板与商家端定稿一致：`--ground #f6f1e7`、`--card #fffdf8`、`--iron #1f3b2f`、`--gilt #c39a3a`、`--accent #b5502f`。深色模式写两份（`[data-theme="dark"]` 与 `system` 下的 `prefers-color-scheme`）；`--scale` 取 0.92 / 1 / 1.1。
- 断点：1180px 购物车改抽屉；760px 首页单列、热门两列、顶栏只留图标；420px 视图标签只留图标。**375px 无横向滚动**。
- 会话 ID 只存内存，不写 URL、cookie 或 localStorage（AGENTS.md §十一、PRD C3）。
- 前端不求和、不乘单价、不算优惠；金额只格式化后端给的整数分。
- 不得用写死的示意数据冒充真实数据（R7）。`rules_summary` 为空串时不渲染规则摘要区。
- 降级必须可见（R7）：`degraded` / `degraded_reason` / 各 `analysis_sources[].degraded_reason` 都要显示。
- 机器译文与缺译回退的标注（`TranslationNote`）在方块、浮层、购物车、订单行上都保留（C9）。
- 热门排序：近 30 个业务日（Asia/Shanghai）已支付订单的件数降序，并列按 `created_at DESC, id DESC`；响应不返回销量数字。
- 图片：`shop/public/demo/products/NN.webp`，800×800，单张 ≤200KB，共 24 张（2026-10-04 用户裁定补上 #06，此前 23 张）；`image_url` 为 `/demo/products/NN.webp`；`ALLOWED_IMAGE_HOSTS` 保持为空。
- 刻意缺口必须保留：#03 无「产地」、#05 说明为“简短说明。”（#06 `image_url = null` 已于 2026-10-04 按用户裁定取消，PRD §8.3 同步）。除此之外，每件商品的属性都要覆盖后端类目必填表（女装/男装/鞋靴：材质、产地、尺码；家居：材质、产地；美妆：产地、保质期），不得产生额外的内容缺口。
- `shop/AGENTS.md`：这是新版 Next.js，写 Next 代码前先读 `shop/node_modules/next/dist/docs/` 里对应的指南（`redirect`、`cookies()`、`next/font`、布局）。
- 不修改 `vendor/`、`yshopping-*` 目录（R8）；`shop/src/api/generated.ts` 与 `frontend/src/api/generated.ts` 禁止手改。

## Review Focus

以下输入规格没有明说，最可能在真人使用时出问题。每条都已在所属任务里加了测试：

1. **订单首件商品已下架或已删除**：订单行仍显示价格快照里的名称，接口不能 500（Task 3 步骤 1 用例 4）。按契约 §8.10.1，已下架商品仍取当前图片；只有商品已删除或图片来源不可信时为 null，前端显示“暂无图片”占位（2026-09-30 审查时按契约校正）。
2. **访客直接打开 `/{shop}/orders` 或旧的 `/{shop}/memories`**：只显示绑定提示，**不发**订单或记忆请求，所以不会出现 403 报错条（Task 11 步骤 1、Task 10 步骤 1）。
3. **语言 cookie 是非法值或被篡改**：回退到 `Accept-Language`，再回退到 zh-CN；服务端渲染与客户端请求的语言保持一致，不会出现半中半英（Task 7 步骤 1）。
4. **对话进行中切换身份（绑定 / 退出）**：旧对话按主体变化规则清空，进行中的流不会写进新主体的对话，目录按新主体重新拉取（Task 8 步骤 1）。
5. **全新店铺没有任何销量**：`sort=popular` 仍返回商品，按上架时间排序，首页热门区不空（Task 2 步骤 1 用例 3）。

---

## 一、文件地图

| 文件 | 职责 |
| --- | --- |
| `docs/PRD.md` | C1、C2、§8.3、§11.2.2 语义、§15 新增「WS」 |
| `docs/backend-development-plan.md` | §8.8.1 `missing_attributes`；§8.8.2 商品列表 `sort`；§8.10.1 `OrderSummary` 两字段；顾客工具契约补 `get_my_order` |
| `backend/app/repositories/v2/catalog.py` | 新增 `recent_paid_quantities()` |
| `backend/app/api/routes/v2/shop_catalog.py` | 商品列表 `sort` 参数、排序键、游标绑定 |
| `backend/app/schemas/v2/shop_session.py`、`backend/app/services/v2/catalog.py` | `ProductDetailResponse.missing_attributes` 与其计算 |
| `backend/app/schemas/v2/trade.py` | `OrderLeadItem`；`OrderSummary.lead_item` / `last_event_at` |
| `backend/app/services/v2/orders.py` | `to_order_summary()` 新签名；`order_leads()`、`last_event_times()` 批量查询 |
| `backend/app/api/routes/v2/shop_orders.py` | 列表、详情、下单、支付、取消五处装配新字段 |
| `backend/app/tools/customer/orders.py` | 新建。`get_my_order` 只读工具 |
| `backend/app/tools/customer/__init__.py` | 注册新工具 |
| `backend/app/skills/customer/after-sales-service/SKILL.md` | 补一句订单进度用 `get_my_order` |
| `backend/app/analytics/demo_data.py` | 24 件真实商品目录、固定价格（保留 rng 调用）、`.webp` 路径 |
| `backend/app/jobs/seed_demo_rolling.py` | `_catalog()` 对未被商家改过的种子行更新内容字段 |
| `backend/app/eval/datasets/security/ws_shop_storefront.yaml` | 新建。改动路由的安全用例 |
| `scripts/demo_product_images.py` | 新建。把用户交付的原图转成 800×800 WebP 并校验（`uv run --with pillow`） |
| `shop/public/demo/products/*.webp`、`IMAGE-CREDITS.md` | 23 张商品图与来源说明 |
| `shop/src/api/client.ts` | 请求自动带 `Accept-Language`（取当前界面语言） |
| `shop/src/api/shopApi.ts`、`catalogApi.ts`、`adapters/shop.ts`、`types/shop.ts` | `listOrders()`、`listPopularProducts()`、`OrderSummaryView` 等 |
| `shop/src/i18n/` | 新建。`messages.ts`（双语字典）、`locale.ts`（cookie 解析）、`LocaleProvider.tsx`、工具显示名映射 |
| `shop/src/preferences/` | 新建。主题与字号的读写、首屏防闪烁脚本、`PreferencesPopover.tsx` |
| `shop/src/chat/ChatProvider.tsx` | 新建。聊天状态（由 `AssistantClient` 迁出） |
| `shop/src/shell/` | 新建。`TopBar.tsx`、`IdentityMenu.tsx`、`CartPanel.tsx`、`Composer.tsx`、`ActivityDrawer.tsx` |
| `shop/src/views/` | 新建。`HomeView.tsx`、`ThreadView.tsx`、`OrdersView.tsx`、`ProductSheet.tsx`、`ProductDetailBody.tsx`、`ProductArt.tsx` |
| `shop/src/session/ShopShell.tsx` | 改为组装上述外壳组件 |
| `shop/src/app/[shop_slug]/…` | 路由按规格 §3.2 调整；`assistant`、`cart`、`memories` 改为重定向 |
| `shop/src/app/globals.css`、`src/styles/shop-tokens.css` | 原型 CSS 拆入；顾客端专有 token |
| `shop/e2e/*.spec.ts` | 改入口，不删断言 |

---

## 二、任务

> **2026-09-30 逐项复核说明**：Task 0–11 的复选框是对照当前代码与测试逐步核实后勾选的，不是批量补勾。
> - 「运行确认失败」类红灯步骤无法事后追溯，勾选依据是对应测试现已存在且通过；Task 0 步骤 3 的历史基线同样未留逐项记录，以进度快照里的整改后全量结果为准。
> - 复核中补齐的缺口：`shop-tokens.css` 五个类目占位色（Task 7）；`rawRequest` 语言请求头测试（Task 7）；外壳视图入口／待付款角标／身份菜单／`?panel=memory`、视图切换保留对话、下单后跳转与关闭抽屉、三条旧路由重定向的单测（Task 8）；商品浮层显示类目（Task 11，为此在契约 §8.8.1 `ProductSummary` 增加源类目 `category`）。
> - 与计划写法不同但行为等价、保留现状：热门排序键内联在路由里（未单独建 `_popular_key`）；`TopBar`／`IdentityMenu`／`Composer` 内联在 `ShopShell`；`?panel=` 用 `history.replaceState` 清除；主体切换时聊天状态整体重建（`directoryVersion` 归零、目录按新会话重新拉取），而不是在原状态上递增。
> - 与计划不同、已说明理由：Task 6 步骤 4 的「顾客 A 列表不含 B 的订单与首件」由 `tests/api/v2/test_shop_orders.py::test_order_list_does_not_expose_another_buyers_lead_item` 覆盖（安全 YAML 断言模型不读响应体，见 `ws_shop_storefront.yaml` 头注释）；Task 11 为订单视图「我的售后」直达详情给 `AfterSalesClient` 增加了 `caseId`，原有测试断言未改，只新增一例。

### Task 0：入口核对

- [x] **步骤 1**：读 `docs/project-progress.md`，确认以下三件事，结果写进进度快照：
  - W Task 5 是否已完成。未完成时，本计划只做 Task 1–6；
  - 当前是谁在导出 `docs/api.json`（W Task 4、N4 B）。在快照里登记本计划 Task 6 的导出时点；
  - N4 B Task 8（顾客记忆页）的状态。已完成的话，Task 10 迁移它的逻辑；未完成的话，与其执行者约定直接在动态抽屉里实现。
- [x] **步骤 2**：确认默认演示店铺至少有一位演示顾客，且 v2 订单覆盖待发货、运输中、派送中、已签收与已关闭状态。不足时，在 `backend/scripts/seed_demo_scenarios.py` 里补确定性种子，否则首页“进行中的订单”在演示时是空的。
  - **待付款不预置**（2026-09-30 审查校正）：种子按营业日锚定，而待付款只在下单后 30 分钟内合法；预置的待付款单写入即过期，且没有库存占用，超时关单会把 `stock_reserved` 减成负数。种子改为一笔已超时关闭的订单，演示「待付款」与「去支付」请现场下单。
- [x] **步骤 3**：在 `shop/` 执行 `npm run test`、`npm run typecheck`、`npm run lint`，在 `backend/` 执行 `uv run pytest -q`，记录基线结果。已有的失败要先登记，不算本计划引入的。

### Task 1：PRD 与契约同步（先文档，后代码）

**Files:**
- Modify: `docs/PRD.md`（C1、C2、§8.3、§11.2.2 表格说明、§15）
- Modify: `docs/backend-development-plan.md`（§8.8.2、§8.10.1、§8.8.3 之后的顾客工具说明）

- [x] **步骤 1：PRD C1** 在现有要点后追加：

  ```markdown
  - **店铺页形态（2026-09-28 用户裁定，规格 `docs/specs/2026-09-28-shop-storefront-ui-design.md`）**：
    `/{shop_slug}` 为智能助手首页，自上而下为问候与订单概况、快捷提问、进行中的订单、近 30 天热门商品；
    「全部商品」展开区列出全部在售商品，区块头部显示店铺规则摘要（非空时）与已生效优惠券。
  - 热门排序由后端按近 30 个业务日已支付件数确定，不以目录顺序冒充热门，响应不暴露销量数字。
  ```

- [x] **步骤 2：PRD C2** 在「可以做」里追加一条，并在 C2 标题下注明名称：

  ```markdown
  顾客端界面上统一称为「智能助手」（英文 Assistant）。

  - 查询本人本店订单的支付、履约状态与最近履约事件（只读工具 `get_my_order`，`merchant_id + buyer_key` 双重过滤，访客不可用）。
  ```

- [x] **步骤 3：PRD §8.3** 追加：演示目录为规格 §4.1 的 24 件商品。保留三个刻意缺口，图片路径为 `/demo/products/NN.webp`。已部署库由演示刷新任务更新**未被商家修改过**的种子行。
- [x] **步骤 4：PRD §11.2.2** 表格后追加说明（路径不变）：
  - 商品列表接受 `sort=newest|popular`；
  - 订单列表与订单详情的摘要字段增加 `lead_item`、`last_event_at`。
- [x] **步骤 5：PRD §15** 在「W」之后新增「WS · 顾客端店面重设计」小节，内容取规格 §5 的四条（并行关系、token 依赖、与 N4 B Task 8 的关系、实施计划路径）。同时删掉「W」末尾“顾客端 `shop/` 的界面重设计不在 W 内，另行裁定”，改为“见下方「WS」”。
- [x] **步骤 6：契约 §8.8.2** 商品列表那一行：
  - 查询参数改为 `cursor/limit/sort`，`sort: newest / popular`，默认 `newest`；
  - 表后排序说明改为：“商品 `newest` 为 `created_at DESC, id DESC`；`popular` 为近 30 个业务日（Asia/Shanghai）已支付订单件数 DESC，并列 `created_at DESC, id DESC`；游标额外绑定 `sort`，换 `sort` 复用游标返回 `422 INVALID_CURSOR`。”
- [x] **步骤 6b：契约 §8.8.1** `ProductDetailResponse` 一行末尾追加：`missing_attributes: string[]`（0–20 项）——该商品类目在 `REQUIRED_ATTRIBUTES_BY_CATEGORY` 中的必填属性里，属性表缺失或值为空的**源属性名**，按名称升序；类目未登记时为空数组；不做翻译。
- [x] **步骤 7：契约 §8.10.1** 新增一行模型并修改 `OrderSummary`：

  ```markdown
  | `OrderLeadItem` | `product_id: PublicId`；`name: string[1..200]`（取订单首行价格快照名称）；`image_url: ImageUrl或null`（取商品当前图片，经 `is_trusted_image_host` 判定，商品不存在或不可信时为 null） |
  | `OrderSummary` | （原字段不变）；`lead_item: OrderLeadItem`（按订单明细 `created_at, id` 升序的首行）；`last_event_at: UTC datetime`（该订单最新履约事件的 `occurred_at`；不早于 `created_at`） |
  ```

  同时注明：`OrderDetailResponse` 继承这两个字段，下单、支付、取消的响应同样携带。
- [x] **步骤 8：顾客工具说明**。在 §8.8.3 之后追加 `get_my_order`：
  - 参数：`order_id: string[1..128]`，模型只能传这一项，额外字段拒绝；
  - 结果载荷：`payment_status`、`fulfillment_status`、`after_sale_status`、`pay_by`、`items[{name, quantity}]`、`recent_events[{event_type, occurred_at}]`（最多 5 条，时间升序）；
  - 闸门：与 `check_after_sale_eligibility` 相同的归属过滤。失败时抛 `FatalToolError(gate="ownership")`；
  - 写策略 `READ_ONLY`，可并行；
  - `tool_call` / `tool_result` 展示摘要只含状态文字，不含 `buyer_key`、金额以外的内部字段。
- [x] **步骤 9**：全文搜索 PRD 与契约里的“导购助手”“店员”，只改**顾客端界面名称**的用法；Skill 名“导购 Agent”等内部术语保留。

### Task 2：商品目录——热门排序与缺失属性

**Files:**
- Modify: `backend/app/repositories/v2/catalog.py`
- Modify: `backend/app/api/routes/v2/shop_catalog.py:94-139`
- Modify: `backend/app/schemas/v2/shop_session.py:151-159`、`backend/app/services/v2/catalog.py:151-180`
- Test: `backend/tests/api/v2/test_shop_catalog.py`、`backend/tests/unit/schemas/v2/test_shop_session.py`

**Interfaces:**
- Produces: `CatalogReadRepository.recent_paid_quantities(merchant_id: UUID, *, since: date) -> dict[UUID, int]`；路由查询参数 `sort: Literal["newest", "popular"] = "newest"`；`ProductDetailResponse.missing_attributes: list[str]`。

- [x] **步骤 1：写失败测试**（追加到 `test_shop_catalog.py`，沿用文件里的 `_database`、`_ok`、`_set_product` 与 `tests.support.merchant_v2.seed_product / seed_paid_order`）：

  ```python
  @pytest.mark.asyncio
  async def test_popular_sort_orders_by_recent_paid_quantity(
      postgres_app: FastAPI, postgres_client: AsyncClient
  ) -> None:
      database = _database(postgres_app)
      slow = await seed_product(database, MERCHANT_ONE_ID, title="慢销")
      hot = await seed_product(database, MERCHANT_ONE_ID, title="热销")
      warm = await seed_product(database, MERCHANT_ONE_ID, title="温和")
      await seed_paid_order(database, MERCHANT_ONE_ID, hot, quantity=5, days_ago=2)
      await seed_paid_order(database, MERCHANT_ONE_ID, warm, quantity=2, days_ago=3)
      await seed_paid_order(database, MERCHANT_ONE_ID, slow, quantity=9, days_ago=45)  # 窗口外

      body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", sort="popular")

      assert [item["name"] for item in body["items"]] == ["热销", "温和", "慢销"]
      assert "sales" not in json.dumps(body)  # 不暴露销量数字


  @pytest.mark.asyncio
  async def test_popular_sort_ignores_other_shops_sales(
      postgres_app: FastAPI, postgres_client: AsyncClient
  ) -> None:
      database = _database(postgres_app)
      mine = await seed_product(database, MERCHANT_ONE_ID, title="本店")
      older = await seed_product(database, MERCHANT_ONE_ID, title="本店旧品")
      await _set_product(database, older, created_at=datetime.now(UTC) - timedelta(days=30))
      foreign = await seed_product(database, MERCHANT_TWO_ID, title="别家")
      await seed_paid_order(database, MERCHANT_TWO_ID, foreign, quantity=50, days_ago=1)

      body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", sort="popular")

      assert [item["id"] for item in body["items"]] == [str(mine), str(older)]


  @pytest.mark.asyncio
  async def test_popular_sort_without_any_sales_falls_back_to_newest(
      postgres_app: FastAPI, postgres_client: AsyncClient
  ) -> None:
      database = _database(postgres_app)
      base = datetime.now(UTC)
      created = []
      for index in range(3):
          product = await seed_product(database, MERCHANT_ONE_ID, title=f"新品{index}")
          await _set_product(database, product, created_at=base - timedelta(minutes=10 - index))
          created.append(str(product))

      body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", sort="popular")

      assert [item["id"] for item in body["items"]] == list(reversed(created))


  @pytest.mark.asyncio
  async def test_cursor_is_bound_to_the_sort(
      postgres_app: FastAPI, postgres_client: AsyncClient
  ) -> None:
      database = _database(postgres_app)
      for index in range(3):
          await seed_product(database, MERCHANT_ONE_ID, title=f"甲{index}")
      path = f"/api/v2/shop/stores/{SHOP}/products"
      first = await _ok(postgres_client, path, limit=1)

      resp = await postgres_client.get(
          path, params={"limit": 1, "sort": "popular", "cursor": first["next_cursor"]}
      )

      assert resp.status_code == 422
      assert resp.json()["code"] == "INVALID_CURSOR"


  @pytest.mark.asyncio
  async def test_unknown_sort_is_a_validation_error(postgres_client: AsyncClient) -> None:
      resp = await postgres_client.get(
          f"/api/v2/shop/stores/{SHOP}/products", params={"sort": "price"}
      )
      assert resp.status_code == 422
  ```

- [x] **步骤 2：运行确认失败**

  Run: `cd backend; uv run pytest tests/api/v2/test_shop_catalog.py -k "popular or sort" -v`
  Expected: 前四条 FAIL（`sort` 被忽略，按上架时间排序）；`test_unknown_sort_is_a_validation_error` FAIL（返回 200）。

- [x] **步骤 3：仓储方法**（`repositories/v2/catalog.py`）：

  ```python
  async def recent_paid_quantities(self, merchant_id: UUID, *, since: date) -> dict[UUID, int]:
      """近 N 个业务日已支付订单的件数，按商品汇总；只供排序，不对外暴露数字。"""

      rows = await self._session.execute(
          select(OrderItem.product_id, func.sum(OrderItem.quantity))
          .join(Order, Order.id == OrderItem.order_id)
          .where(
              Order.merchant_id == merchant_id,
              OrderItem.merchant_id == merchant_id,
              Order.payment_status == "PAID",
              Order.business_date >= since,
          )
          .group_by(OrderItem.product_id)
      )
      return {product_id: int(total) for product_id, total in rows.tuples().all()}
  ```

  实现前先确认这个类里保存会话的属性名（`self._session` 或其他），按实际名字写。

- [x] **步骤 4：路由**（`shop_catalog.py`）：
  - 新增 `ProductSort = Literal["newest", "popular"]`，参数 `sort: Annotated[ProductSort, Query()] = "newest"`；
  - `_public_scope()` 增加 `filters` 参数，商品列表传 `{"sort": sort}`，券列表传 `{}`；
  - `popular` 时，`since = 业务日今天 − 29 天`。业务时区复用 `app.analytics.demo_data.BUSINESS_TIMEZONE`；若它不是公开常量，改从定义它的模块导入，不要重复定义；
  - 排序键：

  ```python
  def _popular_key(quantities: Mapping[UUID, int]) -> Callable[[Product], tuple[str, str, str]]:
      def key(product: Product) -> tuple[str, str, str]:
          sold = quantities.get(product.id, 0)
          return (
              descending(f"{sold:012d}"),
              descending(product.created_at.isoformat()),
              descending(str(product.id)),
          )

      return key
  ```

  - docstring 更新为两种排序的说明。

- [x] **步骤 5：运行确认通过**

  Run: `cd backend; uv run pytest tests/api/v2/test_shop_catalog.py -v`
  Expected: 全部 PASS（含原有的 newest 用例）。

- [x] **步骤 6：缺失属性——写失败测试**（`test_shop_catalog.py`）：
  1. 类目为「鞋靴」、属性表只有「材质」「尺码」的商品，详情 `missing_attributes == ["产地"]`；
  2. 属性值为空串的必填项同样计入；
  3. 类目为「测试类目」（未登记）时为 `[]`；
  4. 英文请求下仍返回源属性名 `["产地"]`（不翻译）；
  5. 列表接口的条目**没有**这个字段（只在详情里）。
  Schema 单测：超过 20 项、重复名称时校验失败。
- [x] **步骤 7：实现**：`ProductDetailResponse` 加 `missing_attributes: list[str] = Field(max_length=20)`，并在已有的 `model_validator` 里查重；`to_product_detail()` 用 `required_attributes_for(product.category)` 与 `product.attributes` 计算（值不是非空字符串就算缺失），排序后传入。复用 `content_completeness` 里现成的取值函数，不要另写一份判断。
- [x] **步骤 8：运行确认通过**：`uv run pytest tests/api/v2/test_shop_catalog.py tests/unit/schemas/v2/test_shop_session.py -v` 全部 PASS；`uv run ruff check app tests`、`uv run mypy app` 通过。

### Task 3：订单摘要的首件商品与最近更新时间

**Files:**
- Modify: `backend/app/schemas/v2/trade.py`
- Modify: `backend/app/services/v2/orders.py:46-84, 164-183`
- Modify: `backend/app/api/routes/v2/shop_orders.py`（列表、详情、下单、支付、取消五处）
- Test: `backend/tests/unit/schemas/v2/test_trade.py`、`backend/tests/api/v2/test_shop_orders.py`

**Interfaces:**
- Produces:
  - `OrderLeadItem(product_id: str, name: str, image_url: str | None)`；
  - `to_order_summary(order, *, item_count: int, lead_item: OrderLeadItem, last_event_at: datetime) -> OrderSummary`；
  - `to_order_detail(order, items, *, lead_image_url: str | None, last_event_at: datetime) -> OrderDetailResponse`；
  - `async order_leads(session, orders: Sequence[Order]) -> dict[UUID, OrderLeadItem]`；
  - `async last_event_times(session, orders: Sequence[Order]) -> dict[UUID, datetime]`。

- [x] **步骤 1：写失败测试**
  - Schema 单测（`test_trade.py`）：
    1. `OrderSummary` 缺 `lead_item` 或 `last_event_at` 时校验失败；
    2. `last_event_at` 早于 `created_at` 时校验失败；
    3. `lead_item.image_url` 复用 `ImageUrl` 结构校验，拒绝 `javascript:`、反斜杠路径等。
  - API 用例（真实 PostgreSQL；用 `tests.support.trade` 的 `bound_customer`，下单沿用现有订单测试的播种方式）：
    1. 两行订单的 `lead_item.name` 等于首行价格快照名称；`image_url` 等于该商品的 `/demo/products/…` 路径；
    2. 付款后 `last_event_at` 等于 `PAYMENT_CONFIRMED` 事件时间，且列表与详情一致；
    3. 下单、支付、取消三个写接口的响应都带这两个字段；
    4. **首件商品已下架**（把商品 `status` 设为 `OFFLINE`）：列表仍 200，`lead_item.name` 取快照，`image_url` 仍为商品当前图片（契约 §8.10.1 只在商品不存在或不可信时置 null）；
    5. 另一顾客的订单仍统一 403（回归，不因新增查询改变）。

- [x] **步骤 2：运行确认失败**

  Run: `cd backend; uv run pytest tests/unit/schemas/v2/test_trade.py tests/api/v2/test_shop_orders.py -v`
  Expected: 新用例 FAIL（字段不存在）。

- [x] **步骤 3：Schema**（`trade.py`，`OrderSummary` 之前）：

  ```python
  class OrderLeadItem(TradeModel):
      product_id: PublicId
      name: str = Field(min_length=1, max_length=200)
      image_url: ImageUrl | None
  ```

  `OrderSummary` 增加 `lead_item: OrderLeadItem`、`last_event_at: UtcDatetime`，并在现有 `model_validator` 里补 `last_event_at >= created_at` 的检查。

- [x] **步骤 4：服务层**（`orders.py`）：
  - `order_leads()`：一次查询取各订单 `created_at, id` 最小的明细行（窗口函数或 `DISTINCT ON (order_id)`），左连 `Product` 取当前 `image_url`，经 `trusted_image(url, ALLOWED_IMAGE_HOSTS)` 过滤。名称用 `title_snapshot or "—"`，与 `to_order_detail` 现有做法一致；
  - `last_event_times()`：`select(FulfillmentEvent.subject_id, func.max(FulfillmentEvent.occurred_at))`，按 `merchant_id` 与订单 id 列表过滤、分组。没有事件时回退 `order.placed_at`；
  - `to_order_detail()` 的首件从 `items[0]` 取名称，图片由调用方传入的 `lead_image_url` 提供。

- [x] **步骤 5：路由装配**：
  - 列表：分页**之后**只对当前页的订单调用两个批量函数，避免全量查询；
  - 详情、下单、支付、取消：各自查询后调用同一对函数（传单元素列表）；
  - 幂等重放返回的原响应体，在下单时已经带新字段，不需要特殊处理；但要确认幂等缓存里存的是完整响应体。

- [x] **步骤 6：运行确认通过**：同步骤 2 命令全部 PASS；再跑 `uv run pytest tests -k "order or after_sale or cart" -q`，确认没有旧用例因新增必填字段而失败。失败的旧用例按新契约补字段，**不删断言**。

### Task 4：只读订单工具 `get_my_order`

**Files:**
- Create: `backend/app/tools/customer/orders.py`
- Modify: `backend/app/tools/customer/__init__.py`
- Modify: `backend/app/skills/customer/after-sales-service/SKILL.md`
- Test: `backend/tests/unit/tools/test_customer_order_tools.py`（新建）、`backend/tests/integration/v2/test_customer_order_tool.py`（新建）

**Interfaces:**
- Consumes: `app.services.v2.orders.owned_order_filter`、`order_items`、`fulfillment_events`；`app.tools.types.ToolSpec / ToolRole / WritePolicy / ToolOutput / ToolContext`；`app.tools.errors.FatalToolError`。
- Produces: `GetMyOrderArgs(order_id: str)`；`build_order_tools(database) -> tuple[ToolSpec, ...]`，工具名 `get_my_order`。

- [x] **步骤 1：写失败的单元测试**（`test_customer_order_tools.py`）：

  ```python
  from pydantic import ValidationError

  from app.tools.customer.orders import GetMyOrderArgs, build_order_tools
  from app.tools.types import ToolRole, WritePolicy


  def test_args_accept_only_order_id() -> None:
      assert GetMyOrderArgs.model_validate({"order_id": "o-1"}).order_id == "o-1"
      for field in ("buyer_key", "merchant_id", "include_all"):
          try:
              GetMyOrderArgs.model_validate({"order_id": "o-1", field: "x"})
          except ValidationError:
              continue
          raise AssertionError(f"不应接受模型提交 {field}")


  def test_tool_is_customer_read_only() -> None:
      (spec,) = build_order_tools(None)  # type: ignore[arg-type]
      assert spec.name == "get_my_order"
      assert spec.roles == frozenset({ToolRole.CUSTOMER})
      assert spec.write_policy == WritePolicy.READ_ONLY
      assert spec.parallelizable is True
  ```

- [x] **步骤 2：写失败的集成测试**（`test_customer_order_tool.py`，真实 PostgreSQL；构造 `ToolContext` 的方式照抄 `tests/integration/v2/test_shop_after_sales.py` 与 `test_content_gap_tool.py`，`bound_context` 来自 `tests.support.trade`）：
  1. 本人订单：返回 `payment_status`、`fulfillment_status`、`pay_by`、`items`（名称与数量）、`recent_events`（≤5 条、升序）；载荷里没有 `buyer_key`、`merchant_id`；
  2. 同店另一顾客的订单：抛 `FatalToolError`，`gate == "ownership"`；
  3. 别家店的订单：同 2；
  4. 访客（`buyer_key=None`）：同 2；
  5. 非法 id（非 UUID）：同 2；
  6. 历史订单（`lifecycle_origin != "V2"`）：同 2；
  7. 超过 5 条履约事件时只取最近 5 条（按时间升序输出）。

- [x] **步骤 3：运行确认失败**

  Run: `cd backend; uv run pytest tests/unit/tools/test_customer_order_tools.py tests/integration/v2/test_customer_order_tool.py -v`
  Expected: ImportError / FAIL。

- [x] **步骤 4：实现**（`tools/customer/orders.py`）。结构照 `after_sale.py`，写法：

  ```python
  class GetMyOrderArgs(BaseModel):
      model_config = ConfigDict(extra="forbid")

      order_id: str = Field(min_length=1, max_length=128)


  def build_order_tools(database: Database) -> tuple[ToolSpec, ...]:
      async def get_my_order(ctx: ToolContext, args: GetMyOrderArgs) -> ToolOutput:
          target = order_uuid(args.order_id)
          if ctx.session.buyer_key is None or target is None:
              raise FatalToolError(gate="ownership", tool_name="get_my_order", detail="订单不存在、历史订单或不属于当前顾客")
          async with database.session() as session:
              order = (
                  await session.execute(select(Order).where(*owned_order_filter(ctx.session, target)))
              ).scalar_one_or_none()
              if order is None:
                  raise FatalToolError(gate="ownership", tool_name="get_my_order", detail="订单不存在、历史订单或不属于当前顾客")
              items = await order_items(session, order.id)
              events = await fulfillment_events(session, order)
          recent = events[-5:]
          return ToolOutput(
              payload={
                  "payment_status": order.payment_status,
                  "fulfillment_status": order.fulfillment_status,
                  "after_sale_status": order.after_sale_status,
                  "pay_by": pay_by(order).isoformat(),
                  "items": [{"name": item.title_snapshot or "—", "quantity": item.quantity} for item in items],
                  "recent_events": [
                      {"event_type": event.event_type.value, "occurred_at": event.occurred_at.isoformat()}
                      for event in recent
                  ],
              },
              summary="订单状态与履约事件来自后端订单事实；请如实转述，不推测送达时间",
              row_count=1,
          )

      return (
          ToolSpec(
              name="get_my_order",
              roles=frozenset({ToolRole.CUSTOMER}),
              args_model=GetMyOrderArgs,
              write_policy=WritePolicy.READ_ONLY,
              parallelizable=True,
              description="查询本人本店一笔订单的支付、履约状态与最近履约事件；只读，不能修改订单。",
              executor=get_my_order,
          ),
      )
  ```

  `owned_order_filter` 断言 `buyer_key` 非空，所以访客判断必须在调用它**之前**。实现前核对 `ToolOutput` 的实际字段名（`payload`、`summary`、`row_count`），与 `after_sale.py` 保持一致。

- [x] **步骤 5：注册**：`tools/customer/__init__.py` 在 `build_after_sale_tools` 后加 `*build_order_tools(database)`，模块 docstring 的只读工具列表补上 `get_my_order`。
- [x] **步骤 6：Skill**：`after-sales-service/SKILL.md` 第一段后加一句：“顾客问订单进度、物流或付款截止时，用 `get_my_order` 取后端事实；平台没有精确送达时间时明确说明，不推测。”
- [x] **步骤 7：运行确认通过**：步骤 3 命令全 PASS。再跑 `uv run pytest tests/integration/v2/test_shop_chat.py tests/eval -q`，确认工具注册表、Skill 加载和评测集没有因工具数量变化而失败。评测里若有断言顾客工具全集的用例，按新工具更新，并在进度快照写明。

### Task 5：演示目录与已部署数据的更新

**Files:**
- Modify: `backend/app/analytics/demo_data.py:149-194`
- Modify: `backend/app/jobs/seed_demo_rolling.py:46-57`
- Test: `backend/tests/unit/analytics/test_demo_data.py`、`backend/tests/integration/test_demo_determinism.py`、`backend/tests/integration/jobs/test_seed_demo_rolling.py`

- [x] **步骤 1：写失败测试**：
  1. `build_demo_catalog()` 返回 24 行，`title` 等于规格 §4.1 的中文名（逐一断言，列表写在测试里）；
  2. 价格等于规格表（`Decimal("699.00")` 等）；
  3. #03（index 2）`attributes` 没有 `产地`；#05（index 4）`detail_description == "简短说明。"`；#06（index 5）`image_url is None`；
  3b. **没有意外缺口**：对每一行调用 `required_attributes_for(category)`，除 index 2 缺「产地」外，所有必填属性都存在且非空（用于防止美妆漏写「保质期」、服装把「尺码」写成别的键）；
  4. 其余 23 行的 `image_url == f"/demo/products/{index + 1:02d}.webp"`；
  5. **确定性**：同一 seed 两次生成的 `id`、`listed_at` 与改动前一致（先在改动前运行一次，把 index 0、12、23 三行的 `id` 与 `listed_at` 记进测试常量）；
  6. 刷新任务：库里已有一行 `title` 以 `演示商品` 开头、`content_version == 1` 的种子行时，运行 `_catalog()` 后标题、描述、属性、价格、图片路径都更新为新值，`content_version` 加 1；
  7. 刷新任务：商家已修改过的行（`content_version > 1` 或标题不以 `演示商品` 开头）**不被覆盖**；
  8. 刷新任务仍受 `ALLOW_DEMO_DATA_REFRESH` 控制（沿用 `require_demo_refresh_permission` 的既有测试）。
- [x] **步骤 2：运行确认失败**。
- [x] **步骤 3：目录**：
  - 把规格 §4.1 与原型 `RAW` 数组的内容写成模块级常量 `_DEMO_PRODUCTS: Final[tuple[_DemoProduct, ...]]`，字段为中文名、价格、简介、材质或功效、产地、规格键与值；
  - `build_demo_catalog()` 按下标取用。`price` 那一行保留 `rng.uniform(39, 899)` 调用并丢弃结果，写注释说明原因（保持后续 id 与上架日不漂移）；
  - 属性（`source` 仍为 `DEMO`）：
    - 女装、男装、鞋靴：`材质`、`产地`、`尺码`（值取原型的尺码范围）；
    - 家居：`材质`、`产地`，另加原型里的 `尺寸` 或 `容量`；
    - 美妆：`产地`、`保质期`（统一写“未开封 36 个月，开封后 12 个月”），另加原型里的 `功效`、`规格`；
    - index 2 删 `产地`；
  - `short_description` 用简介；`detail_description` 用“简介 + 尺码与保养信息经店家核对。”，index 4 仍为“简短说明。”；
  - `image_url`：index 5 为 None，其余 `/demo/products/{index + 1:02d}.webp`。
- [x] **步骤 4：刷新任务**：`_catalog()` 的插入改为 `on_conflict_do_update`：
  - 冲突键不变（`merchant_id, product_code`）；
  - 只更新 `title`、`short_description`、`detail_description`、`attributes`、`price`、`image_url`，`content_version` 加 1；
  - `where=` 条件为 `Product.content_version == 1` 且 `Product.title.like("演示商品%")`；
  - 库存、状态、上架时间一律不动。
- [x] **步骤 5**：检查 `app/localization/catalog.py:516` 附近对 `build_demo_catalog()` 的引用，确认它依赖的字段仍然存在。
- [x] **步骤 6：运行确认通过**：新用例与 `uv run pytest tests -k "demo or seed or catalog or inventory" -q` 全部 PASS。

### Task 6：OpenAPI、生成类型、Adapter 与安全用例

**Files:**
- Regenerate: `docs/api.json`、`docs/api.md`、`shop/src/api/generated.ts`、`frontend/src/api/generated.ts`
- Modify: `shop/src/types/shop.ts`、`shop/src/api/adapters/shop.ts`、`shop/src/api/shopApi.ts`、`shop/src/api/catalogApi.ts`
- Create: `backend/app/eval/datasets/security/ws_shop_storefront.yaml`
- Test: `shop/src/api/adapters/adapters.test.ts`、`shop/src/api/catalogApi.test.ts`

**Interfaces:**
- Produces（前端）：
  - `interface OrderSummaryView { id; paymentStatus; fulfillmentStatus; afterSaleStatus; totalCents; itemCount; createdAt; payBy; leadItem: { productId: string; name: string; imageUrl: string | null }; lastEventAt: string }`；
  - `Order` 扩展 `leadItem`、`lastEventAt`；
  - `toOrderSummary(raw: S['OrderSummary']): OrderSummaryView`；
  - `listOrders(): Promise<OrderSummaryView[]>`（`limit=20`，只取首页）；
  - `ProductDetail` 扩展 `missingAttributes: string[]`；
  - `listPopularProducts(slug: string, locale?: string): Promise<Product[]>`（`sort=popular&limit=8`）。

- [x] **步骤 1**：按 §三登记后导出：`cd backend; uv run python ../scripts/export_openapi.py`。再分别在 `shop/` 与 `frontend/` 执行 `npm run codegen` 与 `npm run codegen:check`。
- [x] **步骤 2：写失败的 Adapter 测试**：
  - `toOrderSummary` 映射 `lead_item` / `last_event_at`；`image_url` 为 null 时 `imageUrl` 为 null；
  - `toOrder` 同样带这两个字段；
  - `toProductDetail` 映射 `missing_attributes` → `missingAttributes: string[]`；
  - `listPopularProducts` 请求路径含 `sort=popular&limit=8`，并带 `Accept-Language`；
  - `listOrders` 带 `X-Session-Id`，没有会话时抛 `NoSessionError`（与 `getCart` 一致）。
- [x] **步骤 3：实现** → 运行 `npm run test -- adapters catalogApi` 通过。
- [x] **步骤 4：安全用例**（`ws_shop_storefront.yaml`，`introduced_in` 取当时的 `CURRENT_MILESTONE`，格式照 `n2_shop_catalog_public.yaml` 与 `n2_shop_orders.yaml`）：
  - `sort=popular` 对未知店铺：403 `RESOURCE_FORBIDDEN`；
  - 用 `newest` 的游标请求 `popular`：422 `INVALID_CURSOR`；
  - 顾客 A 的订单列表不含顾客 B 的订单，且 `lead_item` 不泄露 B 的商品；
  - 访客请求订单列表：403 `CUSTOMER_BINDING_REQUIRED`，无副作用。
- [x] **步骤 5**：`cd backend; uv run pytest tests/eval/test_security_gate.py tests/api/test_openapi* -q` 通过；§8.0.1 五项逐项打勾，写进进度快照。

### Task 7：token 同步、字体、偏好设置与双语字典（前置：W Task 5 已完成）

**Files:**
- Sync: `shop/src/styles/tokens.css`（`npm run tokens:sync`）
- Modify: `shop/src/styles/shop-tokens.css`、`shop/src/app/layout.tsx`、`shop/src/api/client.ts`
- Create: `shop/src/i18n/messages.ts`、`shop/src/i18n/locale.ts`、`shop/src/i18n/LocaleProvider.tsx`、`shop/src/i18n/toolNames.ts`
- Create: `shop/src/preferences/preferences.ts`、`shop/src/preferences/bootScript.ts`、`shop/src/preferences/PreferencesPopover.tsx`
- Test: `shop/src/i18n/locale.test.ts`、`shop/src/preferences/preferences.test.ts`、`shop/src/preferences/PreferencesPopover.test.tsx`、`shop/src/api/client.test.ts`

**Interfaces:**
- Produces:
  - `type Locale = 'zh-CN' | 'en-US'`；`LOCALE_COOKIE = 'shop_locale'`；
  - `resolveLocale(cookieValue: string | undefined, acceptLanguage: string | null | undefined): Locale`；
  - `async serverLocale(): Promise<Locale>`（服务端组件用，读 `cookies()` 与 `headers()`）；
  - `useLocale(): { locale: Locale; t: (key: MessageKey, vars?: Record<string, string | number>) => string; setLocale: (next: Locale) => void }`；
  - `setRequestLocale(locale: Locale): void`（`client.ts` 模块级，`rawRequest` 在调用方没给时补 `Accept-Language`）；
  - `type Theme = 'system' | 'light' | 'dark'`；`type TextSize = 'sm' | 'md' | 'lg'`；`loadPreferences(): { theme: Theme; size: TextSize }`；`savePreferences(p): void`；`PREFS_KEY = 'borough-shop-prefs'`；
  - `toolDisplayName(toolName: string, locale: Locale): string`（未知名回退原名）。

- [x] **步骤 1：写失败测试**：
  - `resolveLocale`：cookie 为 `en-US` 时返回 en；cookie 为 `fr`、空串、`en-US;drop` 时回退到 `Accept-Language`；两者都无效时返回 zh-CN；
  - `rawRequest`：`setRequestLocale('en-US')` 后请求头 `Accept-Language: en-US`；调用方显式给了请求头时不覆盖；
  - `loadPreferences`：localStorage 的 `getItem` 抛错时返回默认值；存的是非法值时回退默认；
  - `PreferencesPopover`：选深色后 `document.documentElement.dataset.theme === 'dark'` 并写入 localStorage；选大号后 `dataset.size === 'lg'`；选 English 后写入 cookie `shop_locale=en-US` 并调用 `router.refresh()`（mock `next/navigation`）；Esc 关闭并把焦点还给齿轮按钮；
  - `toolDisplayName('search_products', 'zh-CN') === '搜索商品'`；`toolDisplayName('unknown_tool', 'zh-CN') === 'unknown_tool'`。
- [x] **步骤 2：运行确认失败**：`cd shop; npm run test -- i18n preferences client`。
- [x] **步骤 3：实现**：
  - 执行 `npm run tokens:sync`；`shop-tokens.css` 删除与共享 token 重复的暖纸色定义，只保留顾客端专有 token：选中标签的铸铁绿、五个类目占位底色 `--t-dress` 等（取原型 `:root` 与两份深色定义）；
  - 字体：`app/layout.tsx` 用 `next/font/google` 加载 Fraunces、Instrument Sans、Noto Serif SC（600、700）、Noto Sans SC（400、500、700），`display: 'swap'`，把变量挂到 `<html>` 上，`--font-display` 与 `--font-body` 引用这些变量；
  - `bootScript.ts` 导出一段内联脚本字符串：读 localStorage 并设置 `data-theme` / `data-size`，整段包在 try/catch 里；`layout.tsx` 在 `<head>` 用 `<script dangerouslySetInnerHTML>` 注入；
  - 根布局的 `lang` 改为 `await serverLocale()`；
  - 字典：`messages.ts` 收录外壳、首页、对话、抽屉、订单、购物车、偏好、状态标签、事件标签的全部文案（原型 `I18N` 对象可以直接改写成 TS），`MessageKey` 从 zh-CN 字典的键推导；
  - `toolNames.ts` 映射 9 个顾客工具：`search_products` 搜索商品 / Search products，`get_product` 查看商品详情，`get_product_attribute` 查询商品属性，`get_shop_policy` 查询店铺规则，`set_cart_item` 调整购物车，`check_after_sale_eligibility` 判定售后资格，`prepare_after_sale` 准备售后申请，`recall_preferences` 读取偏好，`get_my_order` 查询订单。
- [x] **步骤 4：运行确认通过**；`npm run tokens:check`、`typecheck`、`lint` 通过。

### Task 8：外壳、聊天状态上移与路由

**Files:**
- Create: `shop/src/chat/ChatProvider.tsx`、`shop/src/shell/TopBar.tsx`、`shop/src/shell/IdentityMenu.tsx`、`shop/src/shell/CartPanel.tsx`、`shop/src/shell/Composer.tsx`
- Modify: `shop/src/session/ShopShell.tsx`、`shop/src/session/ShopContext.tsx`、`shop/src/app/globals.css`
- Modify routes: `shop/src/app/[shop_slug]/assistant/page.tsx`、`cart/page.tsx`、`memories/page.tsx`（改为重定向）；新建 `shop/src/app/[shop_slug]/orders/page.tsx`
- Test: `shop/src/session/ShopShell.test.tsx`（改写）、`shop/src/chat/ChatProvider.test.tsx`（新建）、`shop/src/components/cart.test.tsx`（迁到 `CartPanel`）

**Interfaces:**
- Consumes: Task 6 的 `listOrders`；Task 7 的 `useLocale`、`PreferencesPopover`。
- Produces:
  - `useChat(): { messages: ChatMessage[]; busy: boolean; error: string | null; conversationId: string | null; turns: TurnRecord[]; directoryVersion: number; send(text: string): Promise<void>; openConversation(id: string): Promise<void>; resetToNew(): void; onDeleted(id: string): void }`；
  - `ChatMessage = { id; role: 'user' | 'assistant'; text; toolCalls: ToolCall[]; turn?: ChatTurn }`（沿用 `AssistantClient` 的 `Message`）；
  - `TurnRecord = { question: string; turn: ChatTurn; elapsedMs: number }`；
  - `ShopContextValue` 新增 `view: 'assistant' | 'orders'`、`openPanel(panel: 'cart' | 'activity' | 'memory' | 'history'): void`、`closePanel(): void`、`panel: … | null`。

- [x] **步骤 1：写失败测试**：
  - `ShopShell`：顶栏有“智能助手”“订单”两个视图入口，当前视图带 `aria-current="page"`；已绑定时“订单”角标只统计待付款订单（`listOrders` mock 返回两单，其中一单 `PENDING`，断言角标为 1）；访客不请求订单；身份菜单里访客显示「绑定演示顾客」，已绑定显示「退出演示身份」，两者都有“演示身份，非真实登录”；`cart_adjusted=true` 时显示“部分商品因售罄或数量上限已调整。”；
  - `ChatProvider`：沿用 `assistant.test.tsx` 的全部断言（工具行合并、失败时移除空白气泡、降级原因显示、每轮刷新购物车）；另加“视图切到订单再切回，消息仍在”；**主体变化**：绑定后消息清空、`conversationId` 为 null、`directoryVersion` 递增；**流进行中切换主体**：旧流后续事件不写入新主体的消息列表；
  - `CartPanel`：迁移 `cart.test.tsx` 全部断言；新增访客提示“未绑定时刷新后无法找回购物车”；提交订单成功后跳转到 `/{shop}/orders/{新订单 id}`，窄屏时关闭购物车抽屉；下单被拒时逐项列出不可用商品，购物车行不被移除；
  - 路由：`/{shop}/assistant`、`/{shop}/cart`、`/{shop}/memories` 分别重定向到 `/{shop}`、`/{shop}?panel=cart`、`/{shop}?panel=memory`（对 `page.tsx` 调用 mock 的 `redirect` 断言参数）。
- [x] **步骤 2：运行确认失败**。
- [x] **步骤 3：实现**：
  - `ChatProvider` 从 `AssistantClient.tsx` 整体迁出状态与 `send / openConversation / resetToNew` 逻辑。另在 `send` 开始时记录 `performance.now()`，`turn_complete` 时写入 `turns`。为了“流进行中切换主体”，给每次 `send` 带上开始时的 `principalKey`，事件回调里比对，不一致就丢弃；
  - `ShopShell` 组装：`TopBar` + `main`（`children` + `Composer`）+ `CartPanel` + 抽屉插槽 + 左下角 `PreferencesPopover`；读取 `?panel=` 打开对应面板后，用 `router.replace` 去掉这个参数；
  - `Composer`：`aria-label` 为「向智能助手提问」，在订单视图提交时先切回智能助手视图再发送；下方一行演示声明；
  - CSS：把原型的 `.app / .bar / .tabs / .main / .dock / .composer / .cart / .line / .stepper / .fab / .prefs` 拆进 `globals.css`。原型里 `.x span` 这类后代选择器改成 class；
  - 旧的 `assistant/page.tsx`、`cart/page.tsx`、`memories/page.tsx` 改为 `redirect()`。`AssistantClient.tsx`、`CartClient.tsx` 的逻辑已迁出后删除，旧测试文件随组件一起迁移或删除，**断言不丢**。
- [x] **步骤 4：运行确认通过**：`npm run test`、`typecheck`、`lint` 通过。

### Task 9：智能助手首页

**Files:**
- Create: `shop/src/views/HomeView.tsx`、`shop/src/views/ProductArt.tsx`
- Modify: `shop/src/app/[shop_slug]/page.tsx`
- Test: `shop/src/views/HomeView.test.tsx`

**Interfaces:**
- Consumes: `listPopularProducts`、`listProducts`、`getStore`、`listCoupons`（服务端取）；`listOrders`（客户端取）；`useChat().send`；`useShop().openPanel`。
- Produces: `<HomeView popular={Product[]} store={StoreProfile} coupons={Coupon[]} locale={Locale} />`；`<ProductArt product={{ name, imageUrl }} size="tile" | "thumb" />`。

- [x] **步骤 1：写失败测试**（固定 `vi.setSystemTime`）：
  - 问候：20:00 为“晚上好”，已绑定时追加“，欢迎回来”；访客没有后缀；页面上不出现顾客姓名；
  - 概况句：mock 四单（派送中、待付款、运输中、已签收）→ “3 单进行中，1 单今天派送中。1 单待付款。”；访客显示绑定引导；
  - 快捷卡：4 张，点击后以卡片文案调用 `send`，不带其他参数；
  - 进行中的订单：最多 3 行，按派送中 → 待付款 → 运输中 → 已发货 → 待发货排序；待付款行按钮为「去支付」并指向 `/{shop}/orders/{id}`；其余为「问问」，点击后 `send` 的文本包含订单号；访客显示绑定提示且 `listOrders` **未被调用**；
  - 热门：渲染 8 个方块；`LOW_STOCK` 显示“紧张”标签（文案沿用 `lib/labels.ts` 的既有档位名）；`nameTranslationStatus === 'MACHINE'` 时有机器译文标注；
  - `ProductArt`：`imageUrl` 为 null 时渲染“暂无图片”占位；有图时 `<img>` 带 `loading="lazy"`、`width`、`height`、`alt` 为商品名；
  - 全部商品：点击「全部商品」后渲染全部在售商品；`rules_summary` 为空串时**不渲染**规则摘要区；有已生效优惠券时显示券名。
- [x] **步骤 2：运行确认失败**。
- [x] **步骤 3：实现**：
  - `page.tsx`（服务端）用 `serverLocale()` 取语言，并行拉 `getStore`、`listPopularProducts`、`listCoupons`，传给 `HomeView`；
  - `HomeView` 在 `useChat().messages` 非空时让位给 `ThreadView`（Task 10）；
  - 全部商品在点击时由客户端调用 `listProducts` 获取。
- [x] **步骤 4：运行确认通过**。

### Task 10：对话视图与动态抽屉

**Files:**
- Create: `shop/src/views/ThreadView.tsx`、`shop/src/shell/ActivityDrawer.tsx`
- Move: `ConversationDirectory.tsx` → 抽屉「对话记录」页签；`MemoriesClient.tsx` 的逻辑 → 抽屉「我记住的」页签
- Test: `shop/src/views/ThreadView.test.tsx`、`shop/src/shell/ActivityDrawer.test.tsx`；迁移 `conversations.test.tsx`、`MemoriesClient.test.tsx`

- [x] **步骤 1：写失败测试**：
  - `ThreadView`：顾客消息右侧；智能助手消息显示“Borough 智能助手”；有工具调用时显示“查了 N 步”按钮，展开后每行为工具**显示名** + 摘要，不出现参数；`degraded` 为真时显示“本次回答已降级：{原因}”；`analysis_sources` 里降级的来源逐条显示原因；只有最后一条回答显示建议按钮；头部「对话记录」打开抽屉的历史页签，「新对话」调用 `resetToNew`；
  - `ActivityDrawer` 本轮过程：没有轮次时显示空状态；有两轮时可以用 ‹ › 翻看；每行有显示名、状态、摘要和等宽的内部工具名；显示分析来源与用时；
  - 我记住的：迁移 `MemoriesClient.test.tsx` 的全部断言（关闭前的页内确认含条数、确认后清空、逐条删除）；访客显示绑定提示且**不调用** `listCustomerMemories`；
  - 对话记录：迁移 `conversations.test.tsx` 的全部断言（新建、浏览、打开、删除、403 回到新建态）；
  - 抽屉：Esc 关闭并把焦点还给触发按钮；点遮罩关闭；
  - `?panel=memory` 进入时直接打开「我记住的」页签。
- [x] **步骤 2：运行确认失败**。
- [x] **步骤 3：实现**：样式取原型 `.msg-* / .steps / .degraded / .chips / .drawer / .seg / .trace / .mem / .conv`。抽屉是 `role="dialog"`、`aria-modal="true"`，打开后焦点移到关闭按钮。
- [x] **步骤 4：运行确认通过**；删除已迁空的 `memories/MemoriesClient.tsx` 与 `assistant/conversations/`。

### Task 11：订单视图、商品浮层与售后页换样式

**Files:**
- Create: `shop/src/views/OrdersView.tsx`、`shop/src/views/ProductSheet.tsx`、`shop/src/views/ProductDetailBody.tsx`
- Modify: `shop/src/app/[shop_slug]/orders/page.tsx`、`orders/[order_id]/page.tsx`、`products/[product_id]/page.tsx`、`after-sales/AfterSalesClient.tsx`（只换样式）
- Test: `shop/src/views/OrdersView.test.tsx`、`shop/src/views/ProductSheet.test.tsx`；迁移 `order.test.tsx`、`components.test.tsx`

- [x] **步骤 1：写失败测试**：
  - `OrdersView`：分“进行中 / 已完成 / 我的售后”三组；点行原地展开，展开时调用 `getOrder` 与 `listOrderEvents`；待付款显示「去支付」「取消订单」，支付沿用幂等键逻辑（迁移 `order.test.tsx` 的断言）；已签收且 `afterSaleStatus === 'NONE'` 显示「申请售后」，链接为 `/{shop}/after-sales?order={id}`；每单有「问问智能助手」；访客显示绑定提示且**不调用** `listOrders`；`/{shop}/orders/{id}` 进入时该单默认展开；
  - `ProductSheet`：打开时拉 `getProduct`；显示类目、价格、档位、短描述、属性表；规格里的必需属性缺失时显示“店家暂未提供 · 问问智能助手”，点击后 `send` 的文本含商品名与属性名；售罄时加购按钮禁用；Esc 关闭并还原焦点；
  - `products/[product_id]/page.tsx` 服务端渲染用的是同一个 `ProductDetailBody`（断言关键文案一致）。
  - 缺口行：`missingAttributes` 里的每个名称在属性表末尾显示一行“店家暂未提供 · 问问智能助手”；为空数组时不显示缺口行。名称的英文用 `messages.ts` 里的固定词表（产地 Origin、材质 Material、尺码 Size、保质期 Shelf life），未登记的名称原样显示。前端不自己判断哪些属性缺失。
- [x] **步骤 2：运行确认失败**。
- [x] **步骤 3：实现**：
  - 热门方块与全部商品方块点击打开 `ProductSheet`（客户端状态，不改 URL）；
  - `AfterSalesClient` 只替换外层结构与 class，逻辑与测试不动，`AfterSalesClient.test.tsx` 必须原样通过。
- [x] **步骤 4：运行确认通过**。

### Task 12：接入商品图片（前置：用户交付原图）

**Files:**
- Create: `scripts/demo_product_images.py`
- Create: `shop/public/demo/products/NN.webp`（23 张）、`shop/public/demo/products/IMAGE-CREDITS.md`
- Test: `backend/tests/unit/analytics/test_demo_product_images.py`

- [x] **步骤 1：写失败测试**（`test_demo_product_images.py`，不依赖 Pillow）：遍历 `build_demo_catalog()`，对每个非空 `image_url` 断言 `shop/public` 下存在对应文件、大小 ≤200KB；断言目录下没有多余的 `.webp`，也没有 `06.webp`。资源测试及异常目录测试通过，详见进度快照。
- [x] **步骤 2：写转换与校验脚本** `scripts/demo_product_images.py`：
  - `convert <源目录>`：按文件名前缀 `NN` 匹配编号，居中裁成正方形，缩放到 800×800，以 WebP 质量 80 保存；超过 200KB 时按 75、70 递减重试；
  - `check`：校验 23 个文件的尺寸、格式、大小；
  - 运行方式：`cd backend; uv run --with pillow python ../scripts/demo_product_images.py convert <源目录>`，不改项目依赖。
- [x] **步骤 3**：用户将 23 张原图放在 `shop/public/demo/products/`。转换后 WebP 写入同目录；PNG 原图归档到仓库外的 `D:\borough-product-originals`，并写入 `IMAGE-CREDITS.md`（GPT Image、2026-10-01，以及“为本项目生成的虚构商品图，不含真实品牌”）。
- [x] **步骤 4**：图片工具测试通过；S1 店面 E2E 使用脚本化 Fake LLM，补充真实图片加载断言后 4/4 通过。1440px / 375px 页面截图已检查，图片解码为 800×800，375px 无横向溢出；23 个生产静态 URL 均返回 `200 image/webp`。
- [x] 原图已交付，Task 12 不再挂起；06 号商品按规格无图，其他商品请求失败时保留“暂无图片”降级占位。

验收入口：`cd backend; uv run --with pillow pytest tests/unit/analytics/test_demo_product_images.py -q`。
正式资源检查：`uv run --with pillow python ../scripts/demo_product_images.py check`。转换拒绝覆盖已有图片或目标目录中的多余图片；本轮原 PNG 已另存到仓库外，应用静态目录只保留最终 WebP 与来源说明。

### Task 13：端到端测试、验收与文档

**Files:**
- Modify: `shop/e2e/s1-presale-to-payment.spec.ts`、`shop/e2e/conversations-responsive.spec.ts`、`shop/e2e/memories-responsive.spec.ts`、`shop/e2e/s4/*`
- Modify: `backend/tests/support/e2e_s1_app.py`（脚本化模型加一段 `get_my_order` 调用）
- Create: `shop/e2e/storefront-home.spec.ts`
- Modify: `docs/project-progress.md`、`docs/project-navigation.md`、`frontend/prototypes/README.md`

- [x] **步骤 1：改入口，不删断言**：
  - “店铺导航”改为“店铺视图”；“向导购助手提问”改为“向智能助手提问”；
  - “去结账”链接改为右侧购物车的「提交订单」；
  - `search_products` 等工具名断言改为先点“查了 N 步”再断言显示名，或者打开动态抽屉断言内部名；
  - “订单详情”标题改为订单视图里展开的那一单；
  - 会话目录与记忆两个响应式用例改为从动态抽屉进入，375px 无横向滚动的断言保留。
- [x] **步骤 2：新增 `storefront-home.spec.ts`**：
  - 访客首页：显示绑定引导，不出现订单请求失败的报错；
  - 绑定后首页：出现进行中的订单；
  - 点快捷卡：进入对话；
  - 订单「问问」：脚本化模型调用 `get_my_order`，回答里出现状态文字；
  - 偏好切 English：刷新后界面、商品名与智能助手回答都是英文；
  - 旧路由 `/assistant`、`/cart`、`/memories` 正确跳转；
  - 375px 下首页、购物车抽屉、动态抽屉、偏好面板都无横向滚动。
- [x] **步骤 3：全量验证**：
  - 后端：`uv run pytest`、`ruff`、`mypy app`；
  - `shop/`：`npm run test`、`typecheck`、`lint`、`codegen:check`、`tokens:check`、`build`；
  - `frontend/`：`npm run codegen:check`（api.json 变了）；
  - Playwright：`npx playwright test` 与 `npx playwright test -c playwright.s4.config.ts`。
- [x] **步骤 4：文档**：
  - `project-progress.md` 写入 WS 的完成项、未完成项（例如图片未交付）、验证结果，以及“未执行 Git、未调用真实 LLM”；
  - `project-navigation.md` 更新 `shop/src` 的新目录（`i18n/`、`preferences/`、`chat/`、`shell/`、`views/`）与删除的旧文件；
  - 原型 README 注明已实施。

---

## 三、与 W、N4、N5 的衔接和冲突规则

| 对方任务 | 撞点 | 规则 |
| --- | --- | --- |
| W Task 4（商家三条路径导出） | `docs/api.json`、两端 `generated.ts` | 与本计划 Task 6 串行，先到先导；后导出者必须基于前者的结果重新导出，改前在进度快照登记 |
| W Task 5（token 与外壳） | `frontend/src/assets/tokens.css` → `shop` 同步副本 | 本计划 Task 7 起必须在它之后；W 后续再改 token 时，`shop` 重新执行 `tokens:sync` |
| W 其余任务 | 无文件交集 | 可并行 |
| N4 B Task 0–7（记忆后端） | `docs/api.json` | 导出串行 |
| N4 B Task 8（顾客记忆页） | `shop/src/app/[shop_slug]/memories/` | 若未完成，并入本计划 Task 10，直接做在动态抽屉里；若已完成，Task 10 迁移它的逻辑与测试 |
| N4 C（检索） | Alembic、测试库镜像 | 本计划没有迁移；C 换镜像期间暂停本计划的集成测试 |
| N5 D Task 7（双端演示） | 演示讲解 | 顾客端按新外壳演示；图片未交付时演示“暂无图片”占位并如实说明 |
| W Task 3（商家订单路由） | `services/v2/orders.py`、`schemas/v2/trade.py`：商家订单摘要继承本计划新增的 `lead_item`、`last_event_at`（契约 §8.12.4） | 与本计划 Task 3 串行，先到先做，后做者复用同一批函数；本计划 Task 1 步骤 7 的契约须在两者之前写完 |
| N4 B Task 4（`recall_preferences` 注册） | `backend/app/tools/customer/__init__.py`，以及断言顾客工具全集的评测与 Skill 加载测试 | 与本计划 Task 4 串行，后到者追加不覆盖；工具全集断言最终同时包含两个新工具 |
| 既有测试里的「演示商品」字样（2026-09-28 核对：`tests/integration/services/test_safe_query.py`、`tests/integration/repositories/test_analytics_repository.py`、`test_analytics_detail.py` 共 8 处） | Task 5 换名 | Task 5 步骤 6 的 `-k` 过滤覆盖不到这三个文件，需额外跑一遍，按新名修正，不删断言 |

## 四、完成定义

1. Task 0–13 全部勾选。Task 12 若因图片未交付而挂起，须在进度快照明确写出。
2. 两处契约改动的 §8.0.1 五项齐备；新增安全用例零失败；`get_my_order` 的七类归属用例全部通过。
3. 页面行为符合规格 §2：没有写死的示意数据，降级可见，375px 无横向滚动，访客页面不发会话接口请求。
4. 后端、`shop/`、`frontend/` 全量检查通过；S1、S4 与新增首页 E2E 通过。
5. 进度快照写明已完成、未完成与验证限制，以及未执行 Git、未调用真实 LLM。
