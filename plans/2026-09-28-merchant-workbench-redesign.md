# W · 商家工作台界面重设计 实施计划

> **给执行者：** 用 `superpowers:executing-plans` 逐任务推进。步骤用 `- [ ]` 复选框跟踪。
> **本计划不含任何 Git 提交步骤**（R2）。全程使用 Fake LLM，零费用；新增的三条路由不调用 LLM。
> **进度只在 `docs/project-progress.md` 维护。**

**目标：** 按 2026-09-28 定稿原型重建 Vue 商家端外壳与全部页面，并补齐两块能力：M1 的「经营」首页主指标和「订单」区域。

**姊妹计划：** 顾客端店面重设计 WS，见 `plans/2026-09-28-shop-storefront-redesign.md`。两者共用 token 来源与订单摘要实现，冲突规则见 §三末尾几行。

**阶段定位：** PRD §15「W」。W 插在 N4 剩余任务之前：
- N4 A Task 0 已完成；
- N4 的前端任务（B Task 9、C Task 6 的页面部分）等 W 的 Task 5–7 完成后再做；
- N4 的后端工作可以与 W 并行，冲突规则见 §三。

**规格来源：**
- `docs/PRD.md`：M1（界面结构、管理分组、订单区域）、M2、M3、M11、M12、§11.2.3、§15「W」；
- `docs/backend-development-plan.md` §8.12.4（三条新路径的字段契约）；
- 设计说明 `docs/specs/2026-09-28-merchant-workbench-ui-design.md`；
- 定稿原型 `frontend/prototypes/borough-merchant-redesign.html`（只作视觉与交互参考，不直接搬 DOM 脚本）。

**架构：**
- 字段流向保持 `generated.ts → adapters → types → stores → 组件`，组件不直接消费 `generated.ts`。
- 新外壳 `MerchantShell.vue` 作为布局路由，现有页面全部改为它的子路由。
- 运营助手从整页抽成常驻外壳的 `AssistantRail.vue`，聊天逻辑仍在 `stores/opsChat.ts`，不重写。

---

## 一、文件地图

| 文件 | 职责 |
| --- | --- |
| `backend/app/schemas/v2/merchant_ops.py` | 追加 §8.12.4 的指标总览与订单模型、`SignedMoneyCents` |
| `backend/app/services/v2/metrics_overview.py` | 新建。组合 `AttributionService` 的查询、序列、归因与辅助指标，生成降级字段 |
| `backend/app/services/v2/merchant_orders.py` | 新建。本店订单列表与详情、`buyer_alias` 派生，复用 `services/v2/orders.py` 的投影装配 |
| `backend/app/api/routes/v2/merchant_insights.py` | 新建。`GET /merchant/metrics/overview` |
| `backend/app/api/routes/v2/merchant_orders.py` | 新建。`GET /merchant/orders`、`GET /merchant/orders/{order_id}` |
| `backend/app/eval/datasets/security/` 新 YAML | 三条路径的安全用例（登记到当时的 `CURRENT_MILESTONE`） |
| `frontend/src/assets/tokens.css` | 替换为「市集大厅」token（浅色、深色两份、`--scale`），旧变量名保留并改为指向新值 |
| `frontend/src/layouts/MerchantShell.vue` | 新建。侧栏（品牌与商家切换、四个分组、账号区）+ 主视图 + 助手栏插槽 |
| `frontend/src/components/shell/*` | 新建。`SideNav.vue`、`PreferencesPanel.vue`、`AdminGate.vue`、`AssistantRail.vue` |
| `frontend/src/stores/preferences.ts` | 新建。主题与字号，存 localStorage，读写包 try/catch；语言仍由 `stores/locale.ts` 管 |
| `frontend/src/stores/rail.ts` | 新建。助手栏开关、快捷键、预填后自动打开 |
| `frontend/src/views/HomeView.vue` | 新建。首页：简报卡、主指标面板、需要处理事项、最近订单 |
| `frontend/src/views/OrdersView.vue` / `CatalogView.vue` | 新建。订单页（列表 + 详情抽屉）、商品页（`products/content`） |
| `frontend/src/api/adapters/merchantInsights.ts` / `merchantOrders.ts` | 新建。Adapter 与契约测试 |
| `frontend/src/router/index.ts` | 改为外壳嵌套路由：`/` 为首页，`/ops-assistant` 重定向到首页并打开助手栏，`/today` 重定向到 `/` |
| 现有视图 | `ApprovalListView`、`ApprovalView`、`InventoryView`、`AfterSalesView`、`SignalsView`、`MerchantMemoryView`、`KnowledgeBaseView` 迁入外壳并换样式；`OpsAssistantView`、`TodayView` 的逻辑拆进助手栏与首页后删除 |

---

## 二、任务

### Task 0：入口核对

- [x] **步骤 1**：确认 PRD M1、§11.2.3、§15「W」与契约 §8.12.4 已同步（2026-09-28 已完成）。
- [x] **步骤 2**：在进度快照登记 W 开工，并核对 N4 当前执行者：
  - 谁在改 `MerchantMemoryView.vue`（B Task 9，工作区已有未跟踪草稿）；
  - 谁在导出 `docs/api.json`。
  
  按 §三规则排好顺序。
- [x] **步骤 3**：核对 3 个默认演示商家各有足够的 v2 交易订单（至少 5 单，覆盖待支付、待发货、运输中、已签收、售后中）：
  - 契约规定订单页只列 v2 交易订单；
  - 不足时扩展确定性种子脚本，并记录首页订单数与订单页条数的口径差异（首页指标含历史导入订单）；
  - 页面文案要如实说明这一差异。
- [x] **步骤 4**：核对 `return_rate` 在指标注册表中的单位，确定换算成万分比的算法，写进 Task 2 的测试用例。

### Task 1：Schema

- [x] **步骤 1：写失败测试**（`tests/unit/schemas/v2/`），覆盖以下约束：
  - `SignedMoneyCents` 的上下界；
  - `headline` 的求和一致性与 `change_ratio_bp` 为 null 的条件；
  - `baseline_series` 与本期序列等长；
  - 归因：`STOPPED` 时 `segments` 为空；贡献与剩余合计的恒等式；最多 5 项；
  - `secondary` 恰好 3 项且顺序、单位映射固定；
  - `MerchantOrderSummary` 必须有 `buyer_alias`，且拒绝 `buyer_key` 等额外字段。
- [x] **步骤 2**：确认失败 → 实现 → 确认通过；`ruff`、`mypy app` 通过。

### Task 2：指标总览路由

- [x] **步骤 1：写失败测试**：
  - 单元测试：周期与 `attribute_change` 相同（周一当天、周中、周日三种情况）；超过 5 个类目时 `remaining_*` 的合计正确；
  - 单元测试：任一分项失败时整体 `degraded=true`，失败项为空值，不出现示意数字；
  - 集成测试（真实 PostgreSQL）：数字与分别调用 `query_metrics`、`attribute_change` 工具的结果一致；
  - 集成测试：`analysis_sources` 只含 `DATABASE`，`quality_status=NOT_RUN`；
  - 断言整个请求不调用 LLM 客户端。
- [x] **步骤 2：登记安全用例**：未认证、顾客会话。
- [x] **步骤 3**：确认失败 → 实现 → 确认通过。

### Task 3：订单路由

- [x] **步骤 1：写失败测试**：
  - 列表只含本店的 v2 订单；三项筛选分别生效；
  - 游标绑定筛选条件，换筛选后旧游标返回 `INVALID_CURSOR`；
  - 详情价格快照与顾客端同一订单一致；
  - 他店订单与历史订单返回同一 `RESOURCE_FORBIDDEN` 结构并写审计；
  - 响应不含 `buyer_key`；`buyer_alias` 与售后列表同一顾客的别名相同；
  - 订单摘要继承的 `lead_item`、`last_event_at` 与顾客端同一订单一致。这两个字段来自 WS，本任务与 WS Task 3 串行，见 §三。
- [x] **步骤 2：登记安全用例**：未认证、顾客会话、跨商家详情、伪造游标。
- [x] **步骤 3**：确认失败 → 实现 → 确认通过。

### Task 4：OpenAPI、生成类型与 Adapter

- [x] **步骤 1**：`cd backend; uv run python ../scripts/export_openapi.py`，这一步与 N4 的导出串行，见 §三。然后 `cd frontend; npm run codegen`，`codegen:check` 通过。
- [x] **步骤 2**：写 `merchantInsights.ts`、`merchantOrders.ts` 两个 Adapter 与契约测试，要求：
  - 金额保持整数分；
  - 万分比不在 Adapter 里换算成浮点展示值，交给 `utils/localizedFormat.ts`；
  - 降级字段完整映射。
- [x] **步骤 3**：v2 路径清单哨兵与 OpenAPI 快照测试通过。

### Task 5：token 与外壳

- [x] **步骤 1：写组件测试**：
  - 侧栏四个分组，没有「对话记录」；当前页的 `aria-current` 正确；
  - 偏好面板：主题三档写入 `data-theme`，字号三档写入 `data-size`；localStorage 抛错时页面照常渲染；语言切换走 locale store；
  - 商家切换沿用 `MerchantSwitcher` 的既有行为。
- [x] **步骤 2：替换 `tokens.css`**：
  - 旧变量名保留并指向新值，保证未迁移的组件不崩；
  - 深色模式定义两份：`[data-theme="dark"]` 一份，`system` 下的 `prefers-color-scheme` 一份；
  - 字体自托管 woff2 子集或设 `font-display: swap`，`firstpaint:check` 必须通过。
  - `frontend/src/assets/tokens.css` 同时是顾客端 `shop` 的 token 来源（`shop/scripts/sync-tokens.mjs` 原样复制）：
    - 共享 token 只放两端都用的色板、字体、间距与深色定义；商家端专有样式（侧栏等）放组件或单独文件；
    - 完成后在 `shop/` 执行 `npm run tokens:sync` 与 `tokens:check`，确认顾客端现有页面不崩；
    - 在进度快照写明“W Task 5 已完成”，这是 WS Task 7 的开工前提。
- [x] **步骤 3：改为嵌套路由**：
  - `/` 为首页（本 Task 先放占位，Task 8 填实现）；
  - `/today`、`/ops-assistant` 重定向到首页，后者同时打开助手栏；
  - 更新 `router/index.spec.ts` 与路由注释（去掉「`/` 是运营助手页」的旧说法）。
- [x] **步骤 4**：确认失败 → 实现 → 确认通过；`test`、`typecheck`、`lint`、`build` 通过。

### Task 6：助手栏

- [x] **步骤 1：写组件测试**：
  - 默认收起；侧栏入口、`Ctrl/⌘ + J`（`preventDefault`，输入框聚焦时同样生效）、Esc 都能切换；
  - 页面任意「问助手」都经 `opsChat.prefill()` 预填并打开助手栏，**不发送**；
  - 会话目录在助手栏的「历史」面板里，新建、浏览、打开、删除都要确认；
  - SSE 步骤、降级提示、反馈、猜你想问、图表（`MetricChartPanel`）行为与现行 `OpsAssistantView` 一致；
  - 窄屏下改为抽屉并带遮罩，375px 无横向溢出。
- [x] **步骤 2**：从 `OpsAssistantView.vue` 抽出 `AssistantRail.vue`，迁移完成后删除原整页视图及其测试，逐条核对原测试断言都已迁到新测试。
- [x] **步骤 3：更新 Mock E2E 的入口**：
  - `ops-assistant-conversation.spec.ts`、`ops-assistant-localization.spec.ts`、`s3/ops-assistant-responsive.spec.ts`；
  - `n3/merchant-skills.spec.ts`、`s3`、`s4` 场景中依赖 `/` 为助手页的步骤。
  
  **只改入口，不删断言**。
- [x] **步骤 4**：确认失败 → 实现 → 确认通过。

### Task 7：管理分组与管理员令牌入口

- [x] **步骤 1：写组件测试**：
  - 未持令牌时「管理」分组只显示令牌输入入口，并且**不发任何 `/api/admin/*` 请求**；
  - 只读令牌下知识库没有任何写操作按钮；
  - 令牌只存在内存或既有的 AdminToken 存储里，不写进 URL 或日志；
  - 商家会话凭证从不出现在 `X-Admin-Token` 中，管理员令牌也从不出现在 `Authorization` 或 `X-Session-Id` 中。
- [x] **步骤 2**：`AdminGate.vue` 复用 `AdminTokenDialog.vue`，`KnowledgeBaseView` 迁入外壳。给 N5 的 `OpsStatusView` 预留同一分组位置，但不创建该页面。
- [x] **步骤 3**：确认失败 → 实现 → 确认通过；`e2e/knowledge-base.spec.ts` 改入口后通过。

### Task 8：首页

- [x] **步骤 1：写组件测试**：
  - **简报卡**：
    - 逐条渲染 `items` 的 `title` 与 `evidence`，不把条目拼成一段话；
    - 界面不出现「AI 分析」字样（R7）；`degraded` 为真时显示降级说明；
    - 「问助手」使用 `nextActionPrompt`；
    - 截至时间、生成时间、重新生成与冷却行为沿用 `TodayView`；
    - 「去审批（N）」链接到审批页，N 来自草稿 Store。
  - **主指标面板**：
    - 数字与图表只来自 overview 响应，组件不计算比例或贡献；
    - 趋势图用 ECharts（`useEChart`），并随容器尺寸重绘；
    - 归因列出前 5 项，另起一行显示「其余 N 个类目」；
    - `STOPPED` 与降级时显示原因，不画图；
    - 辅助指标值为 null 时显示「暂无数据」而不是 0；点击后预填问题。
  - **需要处理事项**：聚合库存告警、待商家处理的售后、未忽略的内容缺口信号；按类别筛选，最多 5 行。每个数据源单独失败时只影响自己那一类，并显示该类不可用。
  - **最近订单**：取订单列表前 3 条。
- [x] **步骤 2**：确认失败 → 实现 → 确认通过；删除 `TodayView.vue`，其测试断言迁到 `HomeView.spec.ts`。

### Task 9：订单页与商品页

- [x] **步骤 1：写组件测试**：
  - 订单页：三项筛选、游标翻页，详情抽屉显示价格快照与三个状态维度；顾客只显示 `buyer_alias`；没有任何写操作按钮；
  - 订单页顶部说明只列平台交易链路订单（Task 0 步骤 3 的口径）；
  - 商品页：内容完整度与缺口标签来自 `products/content`，页面不自行判定缺口。
- [x] **步骤 2**：确认失败 → 实现 → 确认通过。

### Task 10：其余页面迁入外壳并换样式

- [x] **步骤 1**：审批列表与详情、库存、售后、顾客信号、知识库逐页换样式。**行为不变**，既有组件测试全部保持通过。
- [x] **步骤 2**：`MerchantMemoryView` 与 N4 B Task 9 的执行者协调：
  - B Task 9 若尚未完成，就直接在外壳里、用新 token 完成；
  - 若已完成，W 只负责换样式；
  - 该页须与「管理」分组中的知识库在视觉和位置上都明确区分（PRD M11）。
- [x] **步骤 3**：旧 token 变量名还有引用时，逐一换成新名；全部清零后删除兼容映射。
  > **部分完成（裁定 N，2026-09-30）**：`frontend/src` 内旧 `--color-*` 等引用 103 处已清零，`src/assets/tokens.legacy.spec.ts` 防回归；`tokens.css` 的兼容映射块保留，只供顾客端 `shop/`（仍有约 80 处引用，经 `tokens:sync` 共享），删除动作移交 WS，WS 清零后删除并勾选本步。
  >
  > **完成（2026-09-30，WS 之后收尾）**：核实 `shop/src` 旧名引用已清零后，删除 `tokens.css` 兼容映射块并 `tokens:sync` 到 `shop/`；`tokens.legacy.spec.ts` 取消对 `tokens.css` 的豁免，顾客端新增同款防回归 `shop/src/styles/tokens.legacy.test.ts`（注入旧名探针已证明能失败）。

### Task 11：验收与文档

- [x] **步骤 1：前端全量检查**：`npm run test`、`typecheck`、`lint`、`codegen:check`、`build`、`firstpaint:check`、`secrets:check`。
- [x] **步骤 2：浏览器验收**：
  - Mock E2E 全部通过；S3、S4、S5–S7 浏览器场景通过（Fake LLM，一次性库）；
  - 1440、1100、820、375 四档宽度，浅色与深色，中文与英文；
  - 截图与定稿原型逐页对照，差异列入记录。
- [x] **步骤 3：后端回归**：`REQUIRE_INTEGRATION_DB=1` 全量回归、`ruff`、`mypy app`；`tests/eval` 安全集零失败。
  > 2026-09-30：全量 4203 passed / 1 failed / 4 skipped，唯一失败属 WS `sort=popular` 契约哨兵（运行期间已由 WS 修正，复跑 111 passed）；`tests/eval` 156 passed；`mypy app` 通过；`ruff check .` 34 处错误均不在 W 文件（N4 压缩 2 处、WS 演示目录 32 处）。
- [x] **步骤 4：同步文档**：
  - `docs/project-progress.md`：W 完成、验证结果、N4 前端任务解锁；
  - `docs/project-navigation.md`：登记新文件；
  - `docs/frontend-development-plan.md`：更新第 16 条；
  - `frontend/prototypes/README.md`：原型状态改为「已实施」。

---

## 三、与 N4、N5 的衔接和冲突规则

| 对方任务 | 撞点 | 规则 |
| --- | --- | --- |
| N4 A（上下文与压缩，后端） | 无文件交集 | 可并行 |
| N4 B Task 0–7（记忆后端） | `docs/api.json`（B 新增 5 条路径） | 导出串行，一次只让一个执行者重写 `api.json` 与两端的 `generated.ts`，改前在进度快照登记 |
| N4 B Task 8（顾客记忆页，`shop/`） | 无，`shop/` 不在 W 范围 | 可并行 |
| N4 B Task 9（商家记忆面板） | `MerchantMemoryView.vue`、路由、侧栏 | 在 W Task 5 完成后做，直接进外壳「运营」分组；与 W Task 10 步骤 2 协调同一执行者 |
| N4 C Task 1–5（检索后端） | Alembic 链、测试库镜像 | W 没有迁移，不受影响；C Task 2 步骤 0 换镜像时 W 暂停集成测试 |
| N4 C Task 6（知识后台索引状态） | `KnowledgeBaseView.vue`、知识后台契约 | 页面部分在 W Task 7 完成后做，建在「管理」分组里；契约部分可以先做 |
| N4 C Task 7（S7 回归） | `frontend/e2e/n3/merchant-skills.spec.ts` | W Task 6 步骤 3 改过入口后，S7 以新入口为基准回归 |
| N5 B Task 3 步骤 3（只读运维看板） | 路由、侧栏、令牌入口 | 放进「管理」分组，复用 `AdminGate`；新 token 与外壳已就绪，直接使用 |
| N5 D Task 7（双端演示） | 演示入口与讲解 | 商家端在新外壳上演示 |
| N5 D Task 9 步骤 1a（E2E 缺口复核） | 两页合并时重建的 E2E | 以 W Task 6 步骤 3 改入口后的版本为准 |
| N5 D Task 1（路由对账） | PRD 路径总数 | 三条新路径已进入 PRD §11.2.3，对账时以 PRD 为准 |
| WS Task 1（顾客端 PRD 与契约同步） | PRD §15（「W」末尾那句“另行裁定”由 WS 改为“见「WS」”）、契约 §8.10.1 | WS 的文档同步不改 W 的内容；W Task 3 开工前须确认 WS Task 1 步骤 7 已写入 |
| WS Task 3（订单摘要 `lead_item` / `last_event_at`） | `services/v2/orders.py`、`schemas/v2/trade.py` | 与 W Task 3 串行，先到先做，后做者复用同一批函数（契约 §8.12.4「与 WS 的共用实现」） |
| WS Task 4–5（顾客工具、演示目录换名） | 演示商品名从「演示商品 NN」换成真实名 | W 的测试和种子不得依赖「演示商品」字样；W Task 0 步骤 3 补订单种子时使用 `build_demo_catalog()` 取商品，不写死名称 |
| WS Task 6（导出与 codegen） | `docs/api.json`、两端 `generated.ts` | 与 W Task 4、N4 串行导出 |
| WS Task 7 起（顾客端外壳） | `frontend/src/assets/tokens.css` 经 `tokens:sync` 复制给 `shop` | WS Task 7 必须在 W Task 5 之后；W 之后再改共享 token，须通知 WS 重新同步 |

---

## 四、完成定义

1. Task 0–11 全部勾选。
2. 三条新路径的字段、OpenAPI、生成类型、Adapter 与哨兵五项齐备（§8.0.1）；安全用例零失败。
3. 首页、助手栏、订单页、管理分组的行为符合 PRD M1；没有任何写死的示意数字（R7）。
4. 前端与后端全量检查通过；Mock E2E、S3、S4、S5–S7 浏览器场景通过。
5. 进度快照写明：已完成与未完成的项、验证限制，以及未执行 Git、未调用真实 LLM。

## 五、2026-09-30 审查整改（用户已授权直接实施）

沿用原计划与契约，不新增产品范围或接口字段。工作区包含未提交的 W/WS/N4 实现，直接在当前文件上作定向修复，不迁移或覆盖其他改动。

- [x] 草稿隔离：`stores/drafts.ts` 用请求版本隔离晚到的结果、错误及 loading；会话重置使在途加载失效。`drafts.spec.ts` 先复现换店与请求乱序。
- [x] 助手输入隔离：`AssistantRail.vue` 在商家身份改变时清空局部输入；`AssistantRail.spec.ts` 先复现手写及预填内容跨店残留。
- [x] 语言刷新：订单、商品、最近订单监听 locale，从第一页重读并丢弃旧语言在途结果；组件测试覆盖中文切英文以及旧响应晚到。检查相关首页区块的相同遗漏。
- [x] SQL 分页：商家订单路由先验证游标，服务按时间/ID 键与 `limit + 1` 查询，仅对窗口内订单统计明细。保留游标格式、签名绑定与审计；补数据库排序索引，验证同时间翻页、锚点删除、非法游标不查订单及查询窗口上限。
- [x] 验证与快照：先观察新增回归失败，再修复通过；运行前端全量单测、类型、lint、生成类型及构建检查，后端定向单元/真实一次性 PostgreSQL 集成与相关安全测试。更新进度快照，列清验证边界。不执行 Git 发布，不调用真实 LLM。

**2026-09-30 核实记录**：前四项实现与测试于同日写入但未勾选、未登记验证；本条补核实。红灯步骤无法追溯，以现有回归断言与代码对照为证据。前端全量 `test` **746 passed**、`typecheck`、`lint`、`codegen:check`、`build` 通过；定向 `drafts` / `AssistantRail` / `OrdersView` / `CatalogView` / `HomeView` 84 passed；后端 `REQUIRE_INTEGRATION_DB=1`（本地 compose PostgreSQL、空 `LLM_API_KEY`）`tests/api/v2/test_merchant_orders.py` 与 `tests/integration/test_w_order_index_migration.py` **14 passed**（含同时间翻页、锚点删除、非法游标不读订单）。未跑后端全量与 Playwright。未调用真实 LLM，未执行 Git 操作。
