# N2 模块总览：六个模块的划分、依赖、难度与出口标准

> **本文件是 N2 的总览，不是实施计划。** 它只回答四件事：N2 拆成哪几个模块、每个模块落在框架的哪一层、
> 难点在哪、怎样算完成。逐步骤的做法仍在各模块自己的实施计划里；本文件与它们冲突时，以实施计划为准，
> 并回头修正本文件。
> **进度只在 `docs/project-progress.md` 维护**；下文「状态快照」标注了日期，过期以进度快照为准。
> **本计划不含任何 Git 提交步骤**（R2），也不触发任何 LLM 调用（R3）。
> 写法仿照 `plans/2026-09-21-n1-module-roadmap.md`；N2 的六份实施计划早在 2026-09-21 写完，本文件只做编组与排序；
> 编组时发现的两处前置条件不一致已于 2026-09-22 经用户裁定改入对应计划（见 §二）。

**目标：** 让 N2（PRD §15「最小双端垂直闭环」）的全部工作有一张可核对的地图：
按框架层次切成模块 A–F，写清依赖、难度、撞点与出口标准，避免执行者在模块之间凭印象排序或重复建设。

**规格来源：** `docs/PRD.md` §15 N2、A2、A3、C1–C5、M5、M10、M13、§12.4、S1、S3；
`docs/backend-development-plan.md` §5.6、§6.9、§6.10、§8.7–§8.14；`AGENTS.md` R2、R3、R4、R5、R7；
审查点见 `plans/2026-09-22-astra-checklist.md` §五；各模块实现模型与审查批次见 `plans/2026-09-22-n2-assignment-and-review.md`。

---

## 一、总览表

| 模块 | 框架层 | 实施计划（`plans/2026-09-21-*.md`） | 步骤 | 难度 | 状态（2026-09-22） | 需 R3 授权 |
| --- | --- | --- | --- | --- | --- | --- |
| **0** 入口核对与 N1 收尾 | 审查 | Astra 清单「入口-N2」、N1 待审项 B1–B4 / D1–D6 / E1–E3 | — | — | ⬜ 未开始 | 否 |
| **A** 工具注册表与工具循环 | Agent 内核：`backend/app/tools/` + `backend/app/agent/loop/` | `n2-tool-loop-and-registry` | 20 | 高 | 🟡 实现完成 10/20（2026-09-22）；余 10 步全部等审查：入口 3 条待 N1 B/D/E 审查，Task 2–4 待 Astra N2-1/N2-2 | 否（全程 Fake LLM） |
| **B** 顾客端交易闭环（S1 后端） | 交易服务 + 顾客 v2 路由：`services/v2/checkout.py`、`payment.py`、`api/routes/v2/shop_*`、`tools/customer/` | `n2-trade-closed-loop` | 22 | 高（并发） | 🟡 Task 1（公开浏览）完成（2026-09-23，Opus 为解锁 E Task 7 末步接手）；Task 0、2–8 未开始；Astra N2-5/N2-6 未审 | 否 |
| **C** 商家草稿审批与库存（S3 后端） | 受控写操作 + 商家 v2 路由：`services/v2/draft_apply.py`、`approval_evidence.py`、`inventory_alerts.py`、`api/routes/v2/merchant_*`、`tools/merchant/` | `n2-merchant-drafts-and-inventory` | 23 | 高（安全核心） | 🟡 20/23（2026-09-23）；Task 1–7、9 完成，Task 8（S3 端到端）等 B Task 3–4；Astra N2-3/N2-4 未审 | 否 |
| **D** 双端会话目录与回答反馈 | 横切服务：`services/v2/conversations.py`、`suggestions.py` + 两端路由与界面 | `n2-conversations-and-feedback` | 13 | 低中 | ⬜ 未开始 | 否 |
| **E** 商家端 Vue v2 迁移（S3 浏览器） | 商家前端：`frontend/src/api/`、`stores/`、`views/` | `n2-merchant-vue-v2-migration` | 18 | 中 | ✅ 18/18（2026-09-23，Task 7 末步随 B Task 1 补齐）；Astra N2-8 未审 | 否 |
| **F** 顾客端 Next.js 工程（S1 浏览器） | 顾客前端：新建 `shop/` | `n2-shop-nextjs-app` | 23 | 中高 | ⬜ 未开始 | 否 |
| | | | **119** | | 已勾选 **10 / 119** | 默认零费用；可选费用点见 §二 |

步骤数按各计划 `- [ ]` 复选框计数，**含入口条件**，已排除页眉里说明用的 `` `- [ ]` ``；与
`docs/project-progress.md`「N2–N5 十五份计划」表逐份一致。

难度不是工作量。A、B、C 定为「高」是因为**错了会静默地错**：A 的闸门漏一类就是越权，B 的占库少一把锁就是超卖，
C 的证据少一步就是模型自批——这三类在单测全绿时都可能成立，所以它们各有 Astra 必审项。
D 量小且套路与 v1 同构；E 是迁移而非新建；F 从零建工程，但业务逻辑全在后端，难点在跨服务共享与凭证纪律。

### 与 PRD §15 N2 各条的对应

| PRD N2 条目 | 模块 |
| --- | --- |
| 工具调用循环与预算（A2）、工具注册表与四类闸门（A3） | A |
| 顾客端：店铺页、商品、购物车、结账占库、模拟支付、订单事件（C1–C5 最小集） | B（后端）+ F（页面） |
| 商家端：草稿审批与变更账本（M10）、库存告警与补货（M5 最小集） | C（后端）+ E（审批与库存界面） |
| S3 所需的确定性最小简报（不调 LLM，来源标注为确定性规则） | C Task 6 + E Task 5 |
| 双端会话目录与回答反馈、猜你想问（§12.4、M13） | D |
| S1、S3 端到端可跑，并有并发与幂等测试 | S1：B Task 7 + F Task 8；S3：C Task 8 + E Task 7 |
| 关键安全集补齐三类，七类零失败后方可验收 | 提示词注入：B Task 8（顾客对话、商品描述、知识文档三入口；顾客对话入口 2026-09-22 由 A Task 6 移入）；越权审批与模型自批：C Task 9 |
| （N1 遗留）评测 Task 7 步骤 3「与冻结基线对照」 | A Task 5 给出 Fake LLM 结构对照；真实模型对照另需 R3 |

---

## 二、依赖与执行顺序

### 模块级依赖

```text
0 入口核对 ──→ A 工具循环 ──┬──→ B 交易闭环 ──┬──→ F 顾客端 Next.js ─┐
                            │     (Task 3–4)   │                       ├──→ D 界面部分（Task 4）
                            │         ↓        │                       │
                            └──→ C 草稿与库存 ─┴──→ E 商家端 Vue ──────┘
   B ‖ C（C Task 1–7 与 B 并行；C Task 8 等 B Task 3–4）
   D 后端部分（Task 1–3）在 B Task 6 + C Task 7 之后
```

### 任务级依赖（比模块级更精确，以此为准）

| 下游任务 | 上游 | 说明 |
| --- | --- | --- |
| A 全部 | N1 会话计划（`SessionContext`、来源状态仓储）、N1 B Task 1–4（`converse()` 与 Fake 工具脚本）、N1 E Task 2（安全门禁在 CI 跑绿） | A 的入口条件原文；N1 D 仍待 Astra 审查，见模块 0 |
| B 全部 | A 完成；N1 C 的 M1、M2、M3、M8；N1 D Task 7 | 顾客工具要注册进 A 的注册表 |
| C Task 1–7 | A 完成；N1 C 的 M1、M3、M4、M5、M8 | 不依赖 B，可与 B 并行（2026-09-22 裁定） |
| C Task 8（S3 端到端） | B Task 3–4 | S3 的「订单扣减库存」依赖真实占库与实扣；已写为 Task 8 的前置复选框 |
| D Task 1–3（后端） | B Task 6、C Task 7（两端 Chat 路由能建会话与回答）；N1 D Task 5（`require_owned()`） | D 的入口条件原文 |
| D Task 4（两端界面） | E Task 1–2（Vue 会话凭证作用域）、F Task 1–2（`shop/` 工程与会话） | 已写为 Task 4 的前置复选框（2026-09-22 裁定） |
| E 全部 | C 完成且 `docs/api.json` 已导出 v2 商家路由；N1 D Task 7 | E 的 `codegen` 读的就是这份导出 |
| E Task 6（v2 Chat 与 SSE） | C Task 7 | 商家 Chat 路由 |
| F 全部 | B 完成且 `docs/api.json` 已导出全部 v2 顾客路由；B Task 2 已把 `EmptyCartMerge` 换成真实合并 | F 入口条件原文 |
| A Task 5（基线对照报告） | A Task 4；N1 E 的质量数据集 | 只用 Fake LLM，只证明结构正确，不证明质量更好 |

### 已裁定的两处前置条件（2026-09-22）

1. **B ‖ C。** 草稿计划原把「B Task 3–4 已完成」写在入口条件，会让整份计划等结账与支付做完；
   按任务内容，只有 Task 8（S3 端到端）真正需要真实下单链路。现已下移为 Task 8 的前置复选框，
   Task 1–7 可与 B 并行，步骤数不变。
2. **D 分两段。** 会话目录计划 Task 4 要改两端界面，原入口条件未写前端依赖；现已在 Task 4 前补入前置复选框，
   Task 1–3 仍可早做（12 → 13 步）。

两项都只是计划文字，不改变产品行为，不涉及 PRD 与契约。

### 并行与冲突规则

1. **`docs/api.json` 与生成类型是 B、C、D 的共同撞点。** 三者都按 §8.0.1「每完成一组路由，同一次变更内导出 OpenAPI、
   codegen、Adapter 与快照测试」。并行时**导出串行化**：一次只让一个执行者重写 `docs/api.json`，导出前先拉最新版本；
   `frontend/src/api/generated.ts` 与 `shop/src/api/generated.ts` 任何情况下禁止手改。
2. **Alembic 链**：N2 里只有 C Task 3（操作证据消费表）新增迁移，接在 N1 的 `20260922_0026` 之后。创建前后都确认
   `uv run alembic heads` 恰好一个 head；同一测试库不得有两个执行者同时升降级。
3. **`backend/app/core/config.py`**：A 新增 `AGENT_LOOP_*` 三项。v2 用 `AGENT_LOOP_MAX_LLM_CALLS`（默认 12），
   **v1 的 `MAX_LLM_CALLS_PER_REQUEST` 不动**。
4. **`backend/app/tools/` 注册表**：B 注册顾客工具、C 注册商家工具，都走 A 的注册表自检；
   新增工具的角色、写策略与闸门由 A 的自检拦截，不在业务计划里绕开。
5. **安全集数据目录** `app/eval/datasets/security/`：A、B、C 各自登记用例（`introduced_in: N2`）。
   `CURRENT_MILESTONE` 只能由里程碑收尾改为 N2，**不得由任一模块提前改**。
6. **推荐顺序：** 模块 0 → A → B ‖ C Task 1–7 → C Task 8 → D 后端、E、F → D 界面 → N2 收尾。
   E 与 F 在各自入口条件满足后互不依赖，由不同执行者并行。
   各模块实现者：A、C 为 Opus，B 为 Sol，D、E 为 Sonnet，F 为 Codex 的 Terra（见 `plans/2026-09-22-n2-assignment-and-review.md`）。

### 费用点

N2 六份计划全程 Fake LLM，**默认零费用**。唯一可选费用点是 N1 评测计划 Task 7 步骤 3
「真实模型下新循环与冻结基线对照」：A 完成后才具备执行条件，但它不属于 N2 出口，
执行前须按 R3 说明接口、次数、模型与费用并取得同意；未授权时保持「待人工验收」。

---

## 三、模块详情

### 模块 0 · 入口核对与 N1 收尾

- **内容：** N2 各计划的入口条件引用的是 N1 **实际落地**的接口，所以开工前要做两件事：
  1. N1 待审项收口：B1–B4（LLM 客户端）、D1–D6（会话身份）、E1–E3（评测骨架）按 Astra 清单审查；
     **模块 D 未审前，A 的入口条件「会话计划已执行完」不算满足**；
  2. Astra 清单「入口-N2」：逐份核对六份 N2 计划的入口条件与 N1 实际接口（`SessionContext`、`converse()`、
     `require_owned()`、`CartMergePort`、迁移号 `0017`–`0026`、`docs/api.json` 已有的 5 条会话路径），
     不一致时按 PRD → 契约 → 计划 → 索引修正，不在实现里自选。
- **性质：** 只读审查 + 必要的计划修正，无业务代码。

### 模块 A · 工具注册表与工具循环

- **框架层与落点：** Agent 内核。`backend/app/tools/`（`types.py`、`registry.py`、`gates.py`、`errors.py`）；
  `backend/app/agent/loop/`（`limits.py`、`runner.py`、`fencing.py`）；`config.py` 加 `AGENT_LOOP_*`；
  测试 `backend/tests/unit/tools/`、`backend/tests/unit/agent/loop/`、`backend/tests/eval/baseline_comparison.py`。
  与冻结的 `graph.py` **并存不替换**。
- **任务：** 1 工具类型与注册表自检 → 2 四类闸门（来源 / 选项 / 护栏 / 审批）→ 3 循环上限与预算公式 →
  4 主循环 → 5 与冻结基线的对照报告 → 6 自检与契约同步（顾客对话入口的提示词注入用例已于 2026-09-22 移交 B Task 8）。
- **难度「高」的依据：**
  - 闸门零 LLM、在工具执行前生效；`FatalToolError` 与 `GuardrailRejection` 两类失败必须分开表达；
  - 模型不能经工具参数改写身份或商家范围（R5）；
  - 轮数、工具、LLM 调用、时间、token 五项上限都要打到边界，超限降级对用户可见（R7）；
  - 外部文本围栏（A11）是提示词注入的第一道防线。
- **出口标准：** Task 1–6 全绿、零费用；§6.9 / §6.10 接口签名与实现一致；v1 上限与 `graph.py` 行为不变；
  基线对照报告写明「Fake LLM 只证明结构正确」；Astra **N2-1、N2-2** 必审通过。
- **本模块不做：** 具体业务工具（归 B、C）、Skill 加载（N3）、上下文压缩（N4，`compaction_max_calls` 暂为 0）、
  v2 Chat 路由与 SSE（B、C 各自接线）。

### 模块 B · 顾客端交易闭环（S1 后端）

- **框架层与落点：** 交易服务与顾客 v2 路由。`api/routes/v2/shop_catalog.py`、`shop_cart.py`、`shop_orders.py`、
  `shop_chat.py`；`services/v2/checkout.py`、`payment.py`、`stock_tier.py`；`tools/customer/`；
  `jobs/close_expired_orders.py`；`tests/integration/v2/test_checkout_concurrency.py`、`tests/e2e/test_s1_presale_to_payment.py`。
- **任务：** 1 店铺与商品公开浏览（C1）→ 2 购物车（C3，含把 `EmptyCartMerge` 换成真实合并）→
  **3 结账事务（C4，核心）** → **4 模拟支付与超时关闭的竞争** → 5 订单列表、详情与履约事件（C5）→
  6 顾客导购工具与 Chat 路由 → 7 S1 端到端 → 8 自检（含顾客对话、商品描述、知识文档三个入口的提示词注入用例）。
- **难度「高（并发）」的依据：**
  - 占库、价格重算、快照在**单一事务**内完成，条件更新是禁止超卖的应用层防线，必须有真实 PostgreSQL 并发测试；
  - 不可用项明确返回清单，不静默调整数量或价格；
  - 支付与超时关闭并发时只有一方生效，占库正确释放；30 分钟未支付关闭由**业务路径自检截止时间**，Cron 只清理；
  - 按 §8.7.3 五元组唯一域幂等；`lifecycle_origin = 'V2'` 并在同事务同步投影；`LEGACY_V1` 订单不接受支付、取消；
  - `buyer_key` 只从会话解析。
- **出口标准：** S1 后端端到端通过；并发超卖与幂等测试在真实 PostgreSQL 零 skip 通过；每组路由的 OpenAPI 导出、
  codegen 与快照测试同次完成；Astra **N2-5、N2-6** 必审通过。
- **本模块不做：** 顾客端页面（F）、售后（N3）、完整 Skill 提示词（N3）、超时关闭的 Cron 接线（N5）。

### 模块 C · 商家草稿审批与库存（S3 后端）

- **框架层与落点：** 受控写操作与商家 v2 路由。`api/routes/v2/merchant_drafts.py`、`merchant_inventory.py`、
  `merchant_brief.py`、`merchant_chat.py`；`services/v2/draft_apply.py`、`approval_evidence.py`、`inventory_alerts.py`；
  `tools/merchant/`（`get_inventory_alerts` 只读、`draft_restock` 草稿）；`jobs/expire_drafts.py`；
  操作证据消费表迁移；`tests/integration/v2/test_draft_apply.py`、`tests/e2e/test_s3_inventory_loop.py`。
- **任务：** 1 库存告警（M5）→ 2 补货草稿工具 → **3 审批证据（按契约 §8.7.9，不另立一套）** →
  **4 应用事务（核心）** → 5 草稿列表、丢弃与过期 → 6 确定性最小当日简报 → 7 商家 Chat 路由 →
  8 S3 端到端 → 9 自检（含越权审批、模型自批用例）。
- **难度「高（安全核心）」的依据：**
  - 草稿是商家侧**所有写操作的唯一出口**（D9）；任何工具路径都不能产生「已批准」状态——模型无法自批；
  - 应用事务的固定顺序：归属检查 → 幂等查询 → 证据消费 → 按草案版本 + 目标版本 + 当时护栏复检 → 原子写入 + 变更账本；
  - 审批证据的 nonce 持久化，并与业务写入**同事务**消费；各类证据错误对外同一中性结构；
    Agent 工具结果、SSE、日志、审计都拿不到证据；
  - 草稿 7 天过期由业务路径自检，不靠 Cron；
  - 最小简报不调 LLM，来源如实标注为确定性规则（R7）。
- **出口标准：** S3 后端端到端通过；应用事务的复检、并发与幂等测试在真实 PostgreSQL 通过；新迁移可升降级、单 head；
  OpenAPI 已导出全部 v2 商家路由（E 的入口）；Astra **N2-3、N2-4** 必审通过。
- **本模块不做：** 完整每日简报 M2 与内容、调价、促销草稿（N3）；审批界面（E）；过期 Cron 接线（N5）。

### 模块 D · 双端会话目录与回答反馈

- **框架层与落点：** 横切服务。`services/v2/conversations.py`（两端共用）、`suggestions.py`（复用 v1 候选生成）；
  `api/routes/v2/shop_conversations.py`、`merchant_conversations.py`、`merchant_feedback.py`；
  `frontend/src/components/chat/ConversationSidebar.vue`；`shop/src/app/[shop_slug]/assistant/conversations/`。
- **覆盖路径：** 两端会话目录 6 条 + 商家回答反馈 1 条（补齐 PRD §11.2 原先无人认领的 7 条）。
- **任务：** 1 会话目录服务与路由 → 2 回答反馈（M13）→ 3 猜你想问（M13）→ 4 两端界面 → 5 自检。
- **难度「低中」的依据：** 两端逻辑对称，同一套游标分页与 `require_owned()`；难点只有两个：
  路径参数 `conversation_id` 与认证 `session_id` 分名（契约 §8.7.7）、以及删除后跨主体不可枚举。
- **出口标准：** 7 条路径实现并导出；两端 375px 宽度无横向溢出（§12.4）；删除当前会话后回到新建态。
- **本模块不做：** 顾客侧回答反馈（PRD 未列路径）、反馈自动入评测集（E6 须人工决定）。

### 模块 E · 商家端 Vue v2 迁移（S3 浏览器）

- **框架层与落点：** 商家前端。`frontend/src/api/credentials.ts`（新增 `merchant-session` 作用域 → `X-Session-Id`）、
  `generated.ts`（codegen 产物）、`adapters/drafts.ts`、`inventory.ts`、`brief.ts`、`chatV2.ts`；
  `types/`、`stores/auth.ts`、`drafts.ts`、`inventory.ts`；`views/ApprovalView.vue`、`InventoryView.vue`、`TodayView.vue`；
  `e2e/s3-inventory-loop.spec.ts`。
- **任务：** 1 会话凭证作用域 → 2 会话交换与切换商家（接 N1 已落地的 `adapters/session.ts`）→ 3 生成类型与 Adapter →
  **4 审批界面（核心）** → 5 库存告警与最小简报视图 → 6 v2 Chat 与 SSE 迁移适配 → 7 S3 浏览器 E2E → 8 自检。
- **难度「中」的依据：** 沿用既有单向字段流，不是新建；难点在审批界面必须展示草案、目标当前值与复检结果，
  **不回显审批证据**，以及 v1 页面在切换完成前保持可用。
- **出口标准：** S3 浏览器 E2E（Fake LLM）通过；`codegen:check` 通过；组件不直接消费 `generated.ts`；
  会话 ID 只在内存与请求头；Astra **N2-8**（抽审，与 F 合审）。
- **本模块不做：** 下线 v1 页面与 Bearer 直连（另行评审）；MCP 凭证管理界面（PRD A8：只经命令行脚本）。

### 模块 F · 顾客端 Next.js 工程（S1 浏览器）

- **框架层与落点：** 新建 `shop/`（Next.js App Router + TypeScript）：工程骨架、`Dockerfile`、`railway.json`、
  漂移检查脚本 `check-generated.mjs` / `check-tokens.mjs`、`src/api/`（`generated.ts`、`client.ts`、`credentials.ts`、
  `adapters/`、`sse.ts`）、`src/styles/`、店铺 / 商品 / 导购 / 购物车 / 订单五类页面、`e2e/s1-presale-to-payment.spec.ts`。
- **任务：** 1 工程骨架与两项漂移检查 → 2 会话与凭证 → 3 店铺页与商品详情（C1）→ 4 导购 Agent（C2 最小集）→
  5 购物车与结账（C3、C4）→ 6 订单与履约（C5）→ 7 部署配置 → 8 S1 浏览器 E2E → 9 自检。
- **难度「中高」的依据：**
  - 与 Vue 端**共享 OpenAPI 类型、设计 token 与图标，不共享框架组件**，靠两项漂移检查防止副本过期；
  - 浏览器直连 Backend，**不用 Next.js API Routes 做代理**；`client.ts` 漏配 base URL 必须响亮失败；
  - SSE 按字节流累积解析，不假设单次读取是完整事件；
  - 会话凭证只存内存；未绑定访客刷新后提示「无法找回购物车」而**不是**「已清空」（PRD C3 裁定）。
- **出口标准：** S1 浏览器 E2E（Fake LLM）通过；两项漂移检查通过；刷新行为与 PRD C3 一致且有测试；
  Astra **N2-8**（抽审）。
- **本模块不做：** 售后页、记忆页（N3、N4）；完整 Skill 导购体验（N3）；Railway 实际部署（N5）；真实用户登录。

---

## 四、N2 整体完成定义

N2 完成当且仅当：

1. A–F 六个模块各自满足上面的出口标准，Astra N2-1 至 N2-6 必审全部通过，N2-7、N2-8 抽审完成；
2. S1、S3 各自在后端端到端与浏览器 E2E 两层通过，并发与幂等测试在真实 PostgreSQL 上零 skip；
3. 关键安全集**七类**全部登记并真实运行、零失败（N1 四类 + 越权审批、模型自批、提示词注入三入口），
   此后 `CURRENT_MILESTONE` 才可改为 N2；
4. 后端全量在 `REQUIRE_INTEGRATION_DB=1` 下零失败、零 skip，`ruff check .`、`mypy app` 通过；
   两个前端的单测、`codegen:check`、类型检查与构建通过；
5. PRD §11.2 中归 N2 的 v2 路径全部实现并导出到 `docs/api.json`，无多余路径；
6. v1 回滚点完好：v1 路由、`complete()`、`MerchantContext`、`graph.py` 与 v1 前端页面仍可用；
7. 可选费用点（真实模型基线对照）要么按授权执行并记录，要么标「待人工验收」——**不得把 Fake LLM 对照说成质量验证**；
8. `docs/project-progress.md` 已记录阶段、验证结果、下一步与风险，`docs/project-navigation.md` 已登记新增文件。

**N2 不包含：** Skill 加载与完整 Skill（N3）、售后闭环（N3）、完整每日简报 M2（N3）、记忆与混合召回（N4）、
上下文压缩（N4）、MCP（N5）、Cron 接线与 Railway 实际部署（N5）。

---

## 五、状态快照与维护规则

- 本节状态截至 **2026-09-22**：N1 模块 C 已完成并复审通过；B、D、E 实现完成、待 Astra 审查；
  N2 六个模块均未开始，总勾选 0 / 120。
- 2026-09-22 已裁定两处前置条件（见 §二「已裁定的两处前置条件」），已同步两份实施计划与进度快照。
- 模块完成后：先在该模块的实施计划里勾选步骤，再更新 `docs/project-progress.md`，最后回到本文件更新 §一 状态列。
  **不要只改本文件。**
- 某模块的实施计划新增或删减步骤时，同步本文件 §一 的步骤数（按复选框计数，含入口条件，排除页眉说明用的
  `` `- [ ]` ``）。
