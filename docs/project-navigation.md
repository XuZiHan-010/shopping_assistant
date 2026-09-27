# 项目导航

本文件承接 `AGENTS.md` 中的详细文件索引与目录说明。`AGENTS.md` 只保留稳定约束、授权边界和按任务入口；
具体「哪个文件负责什么」在这里查。

本文件**不定义接口字段契约**。ChatRequest / ChatResponse / ErrorResponse / SSE 的唯一权威定义是
`docs/backend-development-plan.md` §8，实现结果由 `docs/api.md`（OpenAPI 导出）确认。

当前阶段、最近验证结果和未决风险见 `docs/project-progress.md`。

---

## 一、状态标记

- **[现有]**：文件或目录当前存在，可以直接读取或运行。
- **[参考]**：非规范性只读资料，只用于理解既有行为或可复用模式，不定义产品范围。
- **[规划]**：尚未创建的目标路径。创建前不要假设它已经存在；首次创建后同步更新本文件。

标记会过期。修改某个文件前先用 `ls` / `Glob` 确认它的真实状态，不要仅凭本文件的标记推断。

---

## 二、参考项目与 Prototype

### 2.1 [参考] 原始 Java + Vue 项目

根目录：

```text
yshopping-merchant-ai 4/yshopping-merchant-ai/
```

> **整体只读**，约束见 `AGENTS.md` R8。需要复用其中代码或资源时，复制到新项目路径后再改。

| 路径 | 用途 |
| --- | --- |
| `.../AGENTS.md` | 旧项目开发规则与目录说明 |
| `.../docs/architecture.md` | 旧项目业务流程概览 |
| `.../docs/architecture-detail.md` | 旧项目详细架构 |
| `.../docs/deploy-railway.md` | 旧项目 Railway 部署方式 |
| `.../frontend/src/App.vue` | 原商家助手主界面 |
| `.../frontend/src/components/` | 原聊天、图表、建议、日报组件 |
| `.../frontend/src/assets/styles.css` | 原界面视觉样式 |
| `.../frontend/src/api/client.js` | 原前端 API 协议和 mock 数据 |
| `.../backend/src/main/java/com/yshopping/merchantai/graph/` | 原 Agent 主流程 |
| `.../backend/src/main/java/com/yshopping/merchantai/service/` | 原业务服务与查询逻辑 |
| `.../backend/src/test/` | 原业务行为测试，可用于重构对照 |
| `.../runtime/llm-wiki/` | 原业务知识库、指标说明和记忆 |

需要理解旧行为时可读旧实现和测试，再按 PRD 在新架构中重写，不做逐行翻译。

`docs/yshopping-parity-audit.md` 是历史差异记录，不是当前范围清单或开工前清零门禁。

### 2.2 [现有] 无后端交互 Prototype

```text
yshopping-prototype/
```

| 路径 | 用途 |
| --- | --- |
| `yshopping-prototype/index.html` | Prototype 页面结构和 SVG 图标 |
| `yshopping-prototype/styles.css` | 可参考的视觉样式和响应式布局 |
| `yshopping-prototype/app.js` | 预置问答、图表、附件和反馈交互 |
| `yshopping-prototype/yshopping-logo.svg` | 沿用旧品牌标志；复刻时替换为 `borough-logo.svg`，不要直接拷贝 |

本地预览：

```powershell
cd yshopping-prototype
python -m http.server 4173
```

Prototype 只用于理解既有效果，不代表最终工程结构、产品范围或验收基准，也不连接数据库或 LLM。

### 2.3 [现有] 外部 Commerce Agents 交互沙盘

入口：[`frontend/prototypes/commerce-agents-sandbox.html`](../frontend/prototypes/commerce-agents-sandbox.html)，
可直接用浏览器打开；使用说明与固定上游版本见
[`frontend/prototypes/README.md`](../frontend/prototypes/README.md)。

基于 Claude Code 原页面补充 Anthropic 与 Shopify 的代表性场景，涵盖零售、旅行、电信、票务，
全部使用浏览器内模拟数据。它是辅助研究原型，不属于 Borough 生产入口，也不定义 Borough 的产品范围。
离线交互检查：`node frontend/scripts/check-commerce-sandbox.mjs`。

参考项目可执行增强路线见
[`docs/external-agent-enhancement-roadmap.md`](external-agent-enhancement-roadmap.md)：该文档把 Anthropic 与
Shopify 的可借鉴模式使用旧 P0/P1/P2 标签记录候选任务，不代表当前优先级或相关功能已经实现。

---

## 三、顶层目录

```text
merchant_assistant/
├── AGENTS.md / CLAUDE.md        # 稳定约束与入口（CLAUDE.md 仅 @AGENTS.md）
├── README.md / README.en.md
├── .env.example
├── docker-compose.yml
├── .agents/skills/              # Codex 侧项目 OpenSpec 工作流 Skill
├── .claude/skills/              # Claude 侧同语义副本
├── openspec/config.yaml         # OpenSpec 项目上下文与规则
├── frontend/                    # Vue 3 + TypeScript
├── shop/                        # [现有] Next.js 顾客端（N2 模块 F，见 §4.7）
├── backend/                     # Python 3.12 + FastAPI
├── scripts/                     # seed / OpenAPI 导出等
├── docs/                        # PRD、开发计划、契约导出、设计说明
├── plans/                       # 实施与整改计划（非空，见 §八）
├── yshopping-merchant-ai 4/     # [参考] 只读
├── yshopping-prototype/         # [参考] 只读静态 prototype
└── vendor/                      # [参考] 只读第三方参考项目
```

N1–N5 默认不创建通用 `worker/` 或对象存储；只有出现可量化的异步处理需求并先更新 PRD/部署契约时才引入。

---

## 四、前端文件索引

根目录 `frontend/`，承载既有 Vue 商家端。以下除标注外均为 **[现有]**。
顾客端在 `shop/`（N2，Next.js，见 §4.7），不得混入本节目录。

### 4.1 应用入口

| 路径 | 职责 |
| --- | --- |
| `frontend/src/main.ts` | 创建 Vue 应用，注册 Router、Pinia、i18n 和全局样式 |
| `frontend/src/App.vue` | 全局应用外壳，只放路由出口和全局通知 |
| `frontend/src/router/index.ts` | `/` 是商家运营助手（`OpsAssistantView`，两页合并后取代 v1 `AssistantView`），另有知识库、审批 / 库存 / 今日等路由；`/ops-assistant` 与 `/ops-dashboard` 均为旧地址，前者重定向到 `/`，后者已无页面（回落 `not-found`）；演示会话不使用账号密码 `/login` |
| `frontend/src/assets/` | 全局变量、基础布局和还原自 prototype 的视觉样式 |

### 4.2 页面

| 路径 | 阶段 | 职责 |
| --- | --- | --- |
| `frontend/src/views/KnowledgeBaseView.vue` | 现有 | 知识库维护后台；令牌仅内存持有，通过 `X-Admin-Token` 进入 |
| `frontend/src/views/ApprovalView.vue` | N2 已实现 | `/approvals/:draftId` 草稿审批——商家端所有写操作的唯一出口；审批证据只存组件内存 |
| `frontend/src/views/ApprovalListView.vue` | N3 阶段 C 已实现 | `/approvals` 草稿列表，按 `batch_id` 分组 + 勾选批准；批准整批时对每个勾选的子草稿依次签发新证据再应用，证据同样只存组件内存 |
| `frontend/src/views/InventoryView.vue`、`stores/catalogOps.ts` | N3 阶段 C 扩展 | `/inventory` 库存告警、商品内容完整度及优惠券状态/优惠幅度；列表从 `api/adapters/merchantOps.ts` 接入 v2 游标接口 |
| `frontend/src/views/TodayView.vue` | N2 已实现，N3 阶段 C 扩展 | `/today` 完整简报 + 待批准草稿；条目动作 `emit('fill-input')` 并预填到运营助手后跳转（只填不发）；"重新生成"按钮按后端同一套冷却规则自动禁用/启用 |
| `frontend/src/views/OpsAssistantView.vue` | N3 阶段 C 已实现，两页合并（2026-09-27）后接管 `/` | 商家运营助手：v2 Chat（指标查询归因、商品内容、定价促销、库存、导出、售后、规则口径问答均已接入，写操作以草稿提交）+ v2 会话目录侧栏 + 图表可视化（契约 §8.7.11）；取代已下线的 v1 `AssistantView`。数据在 `stores/opsChat.ts`、`api/adapters/merchantConversations.ts`，侧栏 `components/opsChat/OpsConversationList.vue`；375px 验收 `e2e/s3/ops-assistant-responsive.spec.ts` |
| `frontend/src/views/LoginView.vue` | 不规划 | 真实 SSO 不在当前范围；演示会话交换不是账号密码登录 |

**已下线（两页合并，2026-09-27，`docs/PRD.md` §15 N2 裁定「选项 C」）**：v1 `AssistantView.vue`
（商家助手三栏主页面）与 `OpsDashboardView.vue`（Chat BI / 运维看板）及其专属组件、Store、API
Adapter 已随两页合并移除；v1 **后端**（`graph.py` 冻结基线、`POST /api/chat` 等 v1 兼容接口）
不受影响，继续作为评测基线保留。详见下方「已下线」小节。

### 4.3 布局组件

| 路径 | 职责 |
| --- | --- |
| `frontend/src/components/layout/MerchantSwitcher.vue` | 演示商家切换器，MVP 的唯一身份入口；两页合并后挂在 `OpsAssistantView` 头部 |
| `frontend/src/components/layout/LanguageSwitcher.vue` | 中/英语言切换器；写入 `useLocaleStore()` 并持久化到 localStorage；两页合并后同样挂在 `OpsAssistantView` 头部，另见 `KnowledgeBaseView` |

**已下线（两页合并，2026-09-27）**：v1 专属的 `ConversationDrawer.vue`（移动端会话抽屉）、
`chat/ConversationColumn.vue`、`chat/ChatMessage.vue`、`chat/ChatComposer.vue`、
`chat/ConversationNav.vue`、`chat/DailyReportCard.vue` 随 `AssistantView.vue` 一起移除。

### 4.4 分析与知识库组件

| 路径 | 职责 |
| --- | --- |
| `frontend/src/components/insights/MetricChartPanel.vue` | 折线图、柱状图和饼图；两页合并后 v2 `OpsAssistantView` 复用同一组件（props 收窄为纯 `chart`） |
| `frontend/src/components/knowledge/KnowledgeTree.vue` | 知识库目录树 |
| `frontend/src/components/knowledge/DocumentEditor.vue` | 知识文档编辑 |
| `frontend/src/components/knowledge/AdminTokenDialog.vue` | 管理员令牌输入，仅内存持有 |
| `frontend/src/components/knowledge/ConfirmDeleteDialog.vue` | 非空删除的显式确认 |
| `frontend/src/components/knowledge/PromptDialog.vue` | 通用输入对话框 |

**已下线（两页合并，2026-09-27）**：v1 专属的 `insights/MetricDefinitionPanel.vue`、
`insights/RecommendationPanel.vue`、`insights/DetailTable.vue`（随 `AssistantView.vue` 移除），以及
`analytics/NorthStarCards.vue`、`analytics/TrendChart.vue`、`analytics/CategoryTable.vue`（Chat BI
看板专属，随 `OpsDashboardView.vue` 移除，连同 `stores/analytics.ts`、`api/analytics.ts`、
`api/adapters/analytics.ts`、`types/analytics.ts`）。

### 4.5 状态、API 与类型

| 路径 | 职责 |
| --- | --- |
| `frontend/src/stores/opsChat.ts` | 商家运营助手会话、消息、当前轮次、反馈；两页合并（2026-09-27）后接管 `/`，取代已下线的 v1 `stores/chat.ts` |
| `frontend/src/stores/auth.ts` | 当前演示商家、Token；v2 会话生命周期（按需换取、刷新恢复、改选商家即丢弃旧会话，`callWithSessionRetry`、`registerSessionScopedReset`） |
| `frontend/src/stores/drafts.ts`、`inventory.ts` | v2 草稿列表、库存告警；不持有审批证据，切换会话时自动清空 |
| `frontend/src/stores/knowledge.ts` | 知识库目录和编辑状态 |
| `frontend/src/stores/locale.ts` | `useLocaleStore()`：当前显示语言，localStorage 持久化与自愈式失败兜底 |
| `frontend/src/i18n/index.ts` | `vue-i18n` 实例；`SupportedLocale` 字面量与后端 `app/localization/locales.py` 严格一致 |
| `frontend/src/i18n/keys.ts` | 消息目录类型形状，由 `locales/zh-CN.ts`（事实源）派生；禁止 `t(key as any)` |
| `frontend/src/i18n/locales/zh-CN.ts`、`en-US.ts` | 双语消息目录；`en-US.ts` 用 `satisfies MessageSchema` 校验 key 集合 |
| `frontend/src/utils/errorCopy.ts` | `AppErrorCode` → 展示文案的穷尽映射；`surface`/`action` 是行为分支枚举，不进消息目录 |
| `frontend/src/utils/localizedFormat.ts` | 日期、数字、货币的共享格式化；显式接收 `locale`，不内置默认语言 |
| `frontend/src/utils/chart.ts`、`format.ts` | 图表摘要与单元格格式化的统一入口 |
| `frontend/src/api/client.ts` | API 基础地址的唯一读取点；HTTP 客户端、鉴权和统一错误处理。**不提供同源 `/api` 回退** |
| `frontend/src/api/sse.ts` | `fetch` + `ReadableStream` 的 SSE 解析器（不使用 `EventSource`） |
| `frontend/src/api/chat.ts` | v1 兼容接口封装；两页合并（2026-09-27）后仅 `listDemoMerchants` 仍被业务代码使用（`stores/auth.ts`），其余导出（`submitChat`/`listConversations`/`getConversation`/`deleteConversation`/`submitFeedback`）随 v1 前端页面下线成为文件内死代码，登记为后续清理项，未删除该文件 |
| `frontend/src/api/knowledge.ts` | 知识库维护接口 |
| `frontend/src/api/adapters/merchantConversations.ts` | v2 商家会话目录、Chat 发起、`visualization` → `ChartSeries` 映射 |
| `frontend/src/api/credentials.ts` | 按接口分组装配 `Authorization` 与 `X-Admin-Token`，不做「有什么加什么」 |
| `frontend/src/api/generated.ts` | **由 OpenAPI 生成，禁止手改** |
| `frontend/src/api/adapters/` | 生成类型 → 前端领域模型的唯一转换点，每个 Adapter 配契约测试 |
| `frontend/src/api/mock/` | Mock 传输层，供本地开发与 e2e 使用 |
| `frontend/src/types/` | 消息、图表、建议和质量轨迹的前端领域模型 |
| `frontend/src/composables/useEChart.ts` | ECharts 懒加载与挂载时序 |
| `frontend/src/composables/useAppError.ts` | 统一错误展示 |
| `frontend/src/api/attachments.ts` | **不存在/不规划**；附件已延期，未经范围变更不得创建 |

字段流向是单向的，组件不得直接消费 `generated.ts`，也不得自行做字段转换：

```text
OpenAPI → api/generated.ts → api/adapters/*.ts → types/*.ts → Store → 组件
```

传输字段变化而领域语义不变时，改动可限定在生成类型与 Adapter，Adapter 的契约测试会立刻暴露不兼容；
领域语义变化时，同步受影响的类型、Store、组件与测试。

### 4.6 构建期门禁脚本

| 路径 | 职责 |
| --- | --- |
| `frontend/scripts/check-generated.mjs` | `generated.ts` 漂移检查：重新生成到临时文件并与提交版本比对 |
| `frontend/scripts/check-first-paint.mjs` | 生产构建的首屏静态依赖门禁：阻止 ECharts 进入首屏 |
| `frontend/scripts/check-no-secrets.mjs` | 递归扫描 `dist/`，阻止密钥形态字符串进入构建产物 |
| `frontend/scripts/check-no-mock-payload.mjs` | 阻止 mock 数据进入生产产物 |
| `frontend/scripts/check-fixtures.mjs`、`sync-fixtures.mjs` | 前后端共享 fixture 的一致性 |
| `frontend/scripts/mock-e2e-server.mjs`、`e2e-process.mjs` | e2e 的 mock 后端与进程管理 |
| `frontend/scripts/s3-e2e-server.mjs`、`playwright.s3.config.ts` | S3 浏览器验收：迁移 + 播种一次性库 → 脚本化模型后端（8012）→ Vite（5275）；`npm run test:e2e:s3` |
| `backend/tests/support/e2e_s3_app.py`、`backend/scripts/seed_s3_e2e.py` | S3 验收的确定性后端入口（只替换模型，其余全真实）与种子；库名须 `*_s3_e2e_test` |
| `backend/tests/support/e2e_n3_app.py`、`backend/scripts/seed_n3_e2e.py`、`frontend/e2e/n3/` | N3 S2/S5/S6/S7 双端浏览器验收：真实 API/PostgreSQL + 脚本化 Fake LLM；`frontend/playwright.n3.config.ts` 只接受一次性 `*_s3_e2e_test` 库 |

### 4.7 顾客端 `shop/`（N2 模块 F，Next.js App Router）

与 `frontend/` **零交集**：不 import 对方文件，共享物只有提交进仓库的副本 + 漂移检查
（`npm run codegen:check` / `tokens:check`）。字段流：`OpenAPI → api/generated.ts → api/adapters → types → 状态 → 组件`，
组件与页面不 import `generated.ts`（`src/api/isolation.test.ts` 守着）。

| 文件 | 责任 |
| --- | --- |
| `shop/package.json`、`next.config.ts`、`tsconfig.json`、`eslint.config.mjs`、`vitest.config.ts` | 工程骨架（`output: 'standalone'`） |
| `shop/Dockerfile`、`railway.json`、`.dockerignore` | 独立镜像，监听 `PORT`，健康检查 `/health`；构建期不读 `../docs` 与 `../frontend` |
| `shop/scripts/check-generated.mjs`、`check-tokens.mjs`、`sync-tokens.mjs` | 类型 / token / logo 副本漂移检查与同步 |
| `shop/scripts/e2e-process.mjs` | E2E 子进程管理（参照商家端，不用 Playwright 自带 webServer） |
| `shop/src/api/generated.ts` | codegen 产物，禁止手改 |
| `shop/src/api/client.ts`、`errors.ts` | base URL 漏配响亮失败（不回退同源）、`ApiError` / `NetworkError` / `ApiConfigError` |
| `shop/src/api/credentials.ts` | **会话凭证：只存内存**；导出 `getSession` / `setSession` / `clearSession` / `useSession` / `subscribeSession` |
| `shop/src/api/sessionApi.ts`、`shopApi.ts`、`catalogApi.ts`、`chat.ts`、`conversationsApi.ts` | 会话端点、需会话的购物车/订单、**公开**店铺与商品读取（不碰凭证，服务端组件可用）、Chat 事件流、会话目录（列表 / 逐页取完历史 / 删除） |
| `shop/src/api/adapters/`、`sse.ts` | wire → 领域模型；v2 SSE 按字节流累积解析（`tool_call` / `tool_result` / `turn_complete` / `error`） |
| `shop/src/session/` | `sessionService.ts`（创建访客 / 原地绑定 / 换身份，并发进入合并）、`ShopContext.tsx`、`ShopShell.tsx`（顶栏、身份、购物车角标） |
| `shop/src/checkout/checkout.ts` | 提交订单：`client_request_id` 按提交意图复用、网络重试、不可用项逐项返回 |
| `shop/src/components/` | `ProductCard`、`AttributeTable`、`StockBadge`、`CouponList`、`CartView`、`OrderView`、`AddToCartButton` |
| `shop/src/app/[shop_slug]/` | 店铺页、`products/[product_id]`（服务端渲染）；`assistant`、`cart`、`orders/[order_id]`（客户端渲染） |
| `shop/src/app/[shop_slug]/assistant/conversations/` | 会话目录面板 `ConversationDirectory.tsx`（嵌在导购页内，不是独立路由）；当前对话、打开历史、主体变化回到新建态由 `AssistantClient.tsx` 负责 |
| `shop/src/styles/tokens.css`、`public/borough-logo.svg` | 商家端共享副本（**禁止手改**，`npm run tokens:sync`） |
| `shop/src/styles/shop-tokens.css` | 顾客端追加 token（暖纸底、衬线标题、更大字阶） |
| `shop/e2e/s1-presale-to-payment.spec.ts`、`global-setup.mjs`、`playwright.config.ts` | S1 浏览器 E2E（真实后端 + PostgreSQL + 脚本化模型）；后端侧 `backend/tests/support/e2e_s1_app.py`、`backend/scripts/seed_s1_e2e.py` |
| `shop/e2e/conversations-responsive.spec.ts` | 375px 下会话目录新建 / 浏览 / 跳转 / 删除全程无横向溢出（同一套 S1 后端与种子） |


---

## 五、后端文件索引

根目录 `backend/`，导入根包是 `app`。以下除标注外均为 **[现有]**。

### 5.1 应用入口与配置

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | 创建 FastAPI 应用、注册路由、中间件和生命周期 |
| `backend/app/run.py` | 进程入口 |
| `backend/app/core/config.py` | Pydantic Settings 读取环境变量，含主 Agent 与本地化两套独立预算 |
| `backend/app/core/job_config.py` | 离线 Cron 任务的最小数据库配置基类，不含 Web 服务密钥 |
| `backend/app/core/seed_config.py` | 演示数据滚动 Cron 的最小配置，在 `JobSettings` 上追加显式写权限 |
| `backend/app/core/security.py` | 现有演示 Token 与管理员/只读令牌（v1，不受 N1 会话身份影响） |
| `backend/app/core/session.py` | v2 会话凭证原语：`SessionRole`、`SessionContext`、高熵 Token 生成与指纹、`buyer_alias()` |
| `backend/app/core/logging.py` | 结构化日志与敏感字段脱敏；`redact_sensitive_values` 对 `X-Session-Id`、`Authorization`、`X-Admin-Token` 等凭证键（含嵌套请求头）脱敏 |
| `backend/app/core/errors.py` | 统一业务异常和 API 错误格式 |

### 5.2 API 路由

| 路径 | 职责 |
| --- | --- |
| `backend/app/api/router.py` | 汇总所有 `/api` 路由，含 N1 内唯一落地的 5 条 v2 会话路由 |
| `backend/app/api/dependencies.py` | 商家身份、预算、`get_request_locale()`、限流等依赖注入 |
| `backend/app/api/session_deps.py` | v2 会话鉴权依赖：`require_customer_session` / `require_merchant_session` / `require_bound_customer_session`、`get_session_service`（与 `dependencies.py` 的 v1 依赖并存不混用） |
| `backend/app/api/routes/v2/shop_sessions.py` | `POST /v2/shop/sessions`、`POST /v2/shop/sessions/demo-customer`、`DELETE /v2/shop/sessions/current` |
| `backend/app/api/routes/v2/merchant_sessions.py` | `POST /v2/merchant/sessions`、`DELETE /v2/merchant/sessions/current` |
| `backend/app/api/routes/v2/shop_catalog.py` | 顾客端公开浏览（N2 模块 B Task 1）：`GET /v2/shop/stores/{shop_slug}`、`/products`、`/products/{product_id}`、`/coupons`；映射在 `services/v2/catalog.py`，库存三档在 `services/v2/stock_tier.py`（阈值与商家库存告警共用），券换算唯一出口 `services/v2/coupons.py`，查询在 `repositories/v2/catalog.py` |
| `backend/app/api/routes/chat.py` | `/api/chat` 与会话接口 |
| `backend/app/api/routes/feedback.py` | 回答反馈 |
| `backend/app/api/routes/reports.py` | 每日经营报告；管理员重算 |
| `backend/app/api/routes/exports.py` | CSV 导出（签名 URL） |
| `backend/app/api/routes/knowledge.py` | 管理员知识库目录树、文档 CRUD、业务域维护和手动记忆压缩 |
| `backend/app/api/routes/analytics.py` | Chat BI 管理员总览、分类下钻与汇总重刷 |
| `backend/app/api/routes/admin.py` | `/api/admin/ops/status` 等运维端点 |
| `backend/app/api/routes/metrics.py` | 指标检索和口径查询 |
| `backend/app/api/routes/demo.py` | `/api/demo/merchants` |
| `backend/app/api/routes/health.py` | `/api/health`、`/api/ready` |
| `backend/app/api/routes/attachments.py` | **不存在/不规划**；附件已延期，三个旧候选端点不属于当前路径清单 |

路由只负责认证、参数校验和调用 Service，不写业务查询。

### 5.3 Agent 编排（既有商家端基线）

实际实现是**单文件 LangGraph 图**，不是每节点一个模块。**不存在 `backend/app/agent/nodes/` 目录**，
不要按它建目录或去那里找节点实现。

| 路径 | 职责 |
| --- | --- |
| `backend/app/agent/graph.py` | `GRAPH_NODES` 节点顺序、节点实现方法、条件边与步骤文案 |
| `backend/app/agent/state.py` | 一轮问答共享的 `AgentState` |
| `backend/app/agent/prefilter.py` | 零 LLM 前置闸门：确定性切词、问候语识别与判定入口 |

当前 v1 节点顺序（以 `graph.py` 的 `GRAPH_NODES` 为准，本表随时可能落后）：

```text
load_context → retrieve_knowledge_index → prefilter_question
  ├─（拒绝）──────────────────────────────→ suggest_questions
  └─（通过）→ classify_intent → understand_intent → validate_intent
              → retrieve_knowledge_detail → query_data → compose_answer
              → quality_loop → suggest_questions
→ persist_answer → END
```

`prefilter_question` 的出边是条件边：拒绝时跳过全部 LLM 驱动节点直达 `suggest_questions`。
所有节点通过 `AgentState` 交换数据，不在节点之间传递无类型字典。

**该图自 2026-09-20 起冻结为只读评测基线（O4）**：不再承接新 Skill、工具与写操作，
也不部署为新生产主流程。新内核与它**并存不替换**，见下一节。

### 5.3.1 Agent 新内核（N 路线，部分已创建）

新工具循环不改 `graph.py`，而是建在下列**全新目录**中。模块边界、依赖方向、与既有
`LlmClient` / `LlmBudget` / `safe_query` 的衔接，权威定义在
`docs/backend-development-plan.md` **§5.6 与 §6.9–§6.15**——新模块开工前先读那两节。

| 计划路径 | 职责 | 契约 | 里程碑 |
| --- | --- | --- | --- |
| `backend/app/tools/` | **已创建（N2 模块 A）**：`types.py`（`ToolSpec` / `ToolResult` / `ToolDisplay` / `ToolContext` 等）、`registry.py`（注册自检、按角色出工具面、`build_tool_registry()` 在 `create_app()` 调用）、`gates.py`（工具面 → 身份参数 → 参数校验 → 来源 / 选项 / 护栏 / 审批闸门管线，`DatabaseProvenanceStore` 与审计适配器）、`errors.py`（`FatalToolError` / `GuardrailRejection`）；尚无业务工具 | §6.9 | N2 |
| `backend/app/agent/loop/` | **已创建（N2 模块 A）**：`limits.py`（`LoopLimits`）、`runner.py`（`run_loop()` 主循环、确定性校验、`LoopOutcome`）、`fencing.py`（外部文本围栏 A11）；预算公式 `agent_loop_llm_call_floor()` 在 `app/core/config.py`；尚未接 v2 Chat 路由 | §6.10 | N2 |
| `backend/app/skills/` | **已创建（N3 阶段 A–C）**：`spec.py`、`loader.py`、`registry.py`、`tool.py` 负责安全加载与受信通道；`app/eval/skill_cases.py` 校验用例。`customer/` 有 4 个导购/售后 Skill，`merchant/` 有经营 Skill 和 `customer-service-replies`；记忆 Skill 归 N4 | §6.11 | N3 |
| `backend/app/memory/` | 双端记忆抽取、双重过滤、事实层 / 总结层 | §6.13 | N4 |
| `backend/app/eval/` | 评测集、三层评分与关键安全集硬门禁 | §6.15 | N1 起 |
| `backend/app/knowledge/`（扩展） | 混合召回 + pgvector + 索引原子切换 | §6.14 | N4 |

截至 2026-09-24，`app/eval/`（N1 模块 E）、`app/tools/` 与 `app/agent/loop/`（N2 模块 A）、`app/skills/`（N3 阶段 A）已创建；
`app/memory/` 仍是计划路径，目录不存在。知识库里被排除的目录名 `"指标或调用指标平台mcp的skill"` 与 `app/skills/` 无关，**不是实现**。
`agent/loop/runner.py` 在 N3 阶段 A 加了 `load_skill` 受信通道与单回合加载上限（`LoopLimits.max_skill_loads`）；
草稿应用第 5–7 步由 `services/v2/draft_handlers/`（`__init__.py` 协议与分派表、`restock.py` 补货处理器）按种类执行；
N3 阶段 C（2026-09-25）追加 `price_change.py`、`coupon.py`、`content_change.py` 三个处理器。

**N3 阶段 C（商家经营 Skill，2026-09-25）**：
`app/skills/merchant/{performance-insights,inventory-operations,catalog-listings,pricing-promotions,detail-export,rules-metric-caliber}/`
（`SKILL.md` + `cases.yaml`；前 4 个改编自 `vendor/anthropic-commerce-agents@fd4d592`，后 2 个 Borough 自撰）；
`app/services/v2/attribution.py`（`AttributionService`：指标查询与归因，`net_gmv` 由 Python 侧对
`gross_gmv`/`refund_amount` 做减法，不进 SQL）；`app/services/v2/content_completeness.py`（商品内容必填属性缺口判定）；
`app/tools/merchant/{metrics,pricing,export,definitions,content}.py`（业绩查询归因、定价促销起草、
明细导出、指标口径与规则问答、商品内容起草五组只读/起草工具）。

上下文压缩（§6.12）不单独建目录，随 `app/agent/loop/` 一并实现。

### 5.4 业务服务与领域模块

| 路径 | 职责 |
| --- | --- |
| `backend/app/services/chat_service.py` | 一轮聊天的应用层入口 |
| `backend/app/intent/` | 结构化意图的模型、提示词、服务与白名单（`models.py` / `prompts.py` / `service.py` / `whitelist.py`） |
| `backend/app/services/safe_query.py` | 白名单校验、查询路由和 SQL 模板 |
| `backend/app/metrics/` | 指标目录、字段注释、报表 URL 与 seed |
| `backend/app/knowledge/` | 业务域、路径策略、检索、版本与 wiki 导入 |
| `backend/app/services/answer_service.py` | 回答组织和不同模式分发 |
| `backend/app/services/review_service.py`、`quality_loop.py`、`quality_types.py` | 独立质量审核与有限重试 |
| `backend/app/services/visualization_service.py` | 确定安全的图表字段和类型 |
| `backend/app/services/export_service.py` | 动态生成受权限保护的 CSV；当前不引入对象存储 |
| `backend/app/services/report_service.py` | 每日经营报告 |
| `backend/app/services/chatbi_service.py` | Chat BI 日汇总上卷、窗口总览与问题分类下钻 |
| `backend/app/services/memory_service.py`、`memory_agent.py`、`memory_admin_service.py` | 商家记忆提取、压缩和召回 |
| `backend/app/services/knowledge_admin_service.py` | 知识库后台的文档与业务域维护 |
| `backend/app/services/merchant_scope.py` | v1 商家隔离范围的统一出口 |
| `backend/app/services/resource_scope.py` | v2 统一越权判定 `require_owned()`：目标不存在与不属于当前主体走同一条 403（R5、O1） |
| `backend/app/services/session_service.py` | 可信店铺解析、演示顾客绑定与购物车合并事务边界；`CartMergePort` / `EmptyCartMerge` |
| `backend/app/services/session_reconciliation.py` | 启动时按指纹把 `DEMO_MERCHANT_TOKENS` 与已签发商家会话对账，撤销已移除 issuer 的会话（由 `app/main.py` lifespan 调用） |
| `backend/app/services/suggested_questions.py` | 服务端预置推荐问题 |
| `backend/app/services/seed_service.py` | 演示数据 Seed |
| `backend/app/analytics/` | Chat BI 指标、契约、日期与演示数据 |
| `backend/app/domain/order_status_mapping.py` | v1 订单状态与 v2 三维投影的确定性双向映射 |
| `backend/app/jobs/rebuild_projections.py` | 从追加写事件账本重算并报告订单投影漂移 |
| `backend/scripts/seed_demo_scenarios.py` | 本地 S1–S4 双端场景的确定性 Seed |
| `backend/app/llm/` | `client.py` 抽象（v1 `LlmClient`；v2 `ConversationalLlmClient`、`LlmMessage` / `LlmTurn` 等）、`deepseek.py` 实现（`complete()` + 按 `LLM_PROTOCOL` 委派 `converse*`）、`openai_adapter.py` / `anthropic_adapter.py` 两个协议适配器、`adapter_support.py` 两适配器共用的预算 / 失败分类 / SSE 解析、`fake.py` 测试替身（含 `turns` 工具调用脚本）、`guard.py` 费用防护（**尚未包装 `converse*`**）；契约见后端计划 §6.17 |
| `backend/scripts/llm_smoke.py` | 双协议**真实冒烟**脚本，**会产生费用（R3）**；默认只展示计划，`--yes` 才发请求；不属于默认测试套件，不得被 `app/` 或 `tests/` 导入 |
| `backend/app/jobs/seed_demo_rolling.py` | 专用演示数据库的增量滚动 Seed；需显式写权限与商家集合精确匹配 |
| `backend/app/jobs/chatbi_rollup.py` | Chat BI 日粒度汇总的幂等重刷 CLI |
| `backend/app/jobs/purge_guest_provenance.py` | 清理过期且未绑定的访客会话留下的对话来源状态；Railway 配置 `backend/railway.provenance-cron.json`（Service 尚未创建） |
| `backend/app/services/attachment_service.py` | **不存在/不规划**；附件解析已延期 |

### 5.5 数据库和 Repository

| 路径 | 职责 |
| --- | --- |
| `backend/app/db/session.py` | SQLAlchemy Engine 和 Session |
| `backend/app/db/base.py` | ORM Base 和模型导入 |
| `backend/app/repositories/` | 会话、回答、商家、知识、经营数据与本地化的数据访问出口；`session.py`（v2 会话签发/解析/撤销）与 `provenance.py`（对话来源状态）是 N1 D 新增 |
| `backend/migrations/versions/` | Alembic 数据库版本迁移 |
| `docs/database.md` | 已落地数据表分工、历史回填与迁移验证入口 |

Repository 只负责数据访问，不调用 LLM，也不拼接来自用户的列名。

### 5.6 模型和 API Schema

| 路径 | 职责 |
| --- | --- |
| `backend/app/models/` | 商家、会话/消息、回答/反馈/Reviewer、指标/知识/记忆、本地化，以及 N1 C 的事件、草稿、优惠券、售后与幂等 ORM；N1 D 新增 `session.py`（`AgentSession`）与 `provenance.py`（`ConversationProvenance`） |
| `backend/app/schemas/` | `ChatRequest` / `ChatResponse`、意图、图表、建议、质量协议 |
| `backend/app/schemas/v2/` | v2 纯模型契约（无路由）：`common.py` 共用传输组件；`shop_session.py`、`merchant_session.py`、`trade.py`、`after_sales.py`、`merchant_ops.py`、`drafts.py`、`memory.py` 对应 `docs/backend-development-plan.md` §8.8–§8.14 七组 |
| `backend/app/services/v2/after_sale_*.py`、`after_sales.py`、`refund_calc.py`、`conversation_summary.py`、`customer_signals.py` | N3 B 售后资格、状态迁移、价格快照退款、双端详情、随单摘要及售后信号；商家决定在 `draft_handlers/after_sale_decision.py` |
| `backend/app/api/routes/v2/shop_after_sales.py`、`merchant_after_sales.py`、`merchant_signals.py` | N3 B 双端售后与信号路由；商家详情先写查看审计 |
| `backend/app/api/routes/v2/merchant_catalog.py` | N3 C 商家会话只读商品内容与优惠券列表；租户隔离、签名游标、内容缺口由后端确定 |
| `backend/app/tools/customer/after_sale.py`、`backend/app/tools/merchant/after_sale.py`、`signals.py` | 顾客只读预检、商家售后只读与决定草稿、信号只读；决定必须经审批界面应用 |
| `shop/src/app/[shop_slug]/after-sales/`、`frontend/src/views/AfterSalesView.vue`、`SignalsView.vue` | N3 B 顾客申请确认与双端售后/信号界面；传输层由各自 `api/adapters/afterSales.ts` 适配 |

ORM 模型与 API Schema 分开，禁止直接把 ORM 对象作为外部接口协议。
N1 需要为会话、角色、订单/售后事件、库存、草稿审批与索引版本建立或扩展模型；精确定义先写入
`docs/backend-development-plan.md` §7/§8，再创建迁移。真实账号体系仍不在当前范围。

### 5.7 Prompt 与知识库

| 路径 | 职责 |
| --- | --- |
| `backend/app/prompts/` | 回答、Reviewer、记忆、本地化提示词 |
| `backend/app/intent/prompts.py` | 意图识别提示词 |
| `backend/app/knowledge/wiki_seed.json` | 导入用的团队业务知识种子 |

正式部署后，运行时可编辑知识存入 PostgreSQL，不依赖 Railway 临时文件系统。

### 5.8 本地化

| 路径 | 职责 |
| --- | --- |
| `backend/app/localization/locales.py` | `SupportedLocale`（响应显示语言，仅 `zh-CN`/`en-US`）与 `SourceLanguage`（内容源语言探测，多出 `mixed`/`und`）；语义不同，不得混用 |
| `backend/app/localization/catalog.py` | 确定性中英词典：零 LLM 调用，只覆盖闭集词汇；自由文本走 `LocalizationService` |
| `backend/app/localization/payloads.py` | 会话列表/详情响应的按页本地化 payload 组装 |
| `backend/app/localization/error_messages.py` | 稳定错误 `code` → 双语 `message` 的唯一渲染点 |
| `backend/app/services/localization_service.py` | 受费用保护的批量本地化：按源语言等于目标 / 仅含受保护 token / 词典命中 / 人工译文命中 / 机器缓存命中 / LLM 批量调用级联；超预算降级为目标语言占位，不回落源语言 |
| `backend/app/repositories/localization.py` | 机器译文缓存与资源级人工译文的纯数据访问，按 `merchant_id`/`GLOBAL` 强制隔离 |
| `backend/app/models/localization.py` | 两张隔离表的 ORM |
| `backend/app/prompts/localization.py` | 批量翻译系统提示词，JSON-only，抵御源文本注入；`LOCALIZATION_PROMPT_VERSION` 是缓存键的一部分 |

本地化调用与主 Agent 调用共用费用防护基础设施但**预算独立**：
`Settings.localization_max_calls_per_request` 等不占用 `llm_max_calls_per_request`，
`llm_usage.purpose` 用 `AGENT`/`LOCALIZATION` 区分两条费用曲线。

---

## 六、数据库表清单

下表是当前已落地 v1 表族的导航快照；目标数据需求以 PRD §8 为准，精确模型在 N1 写入
`docs/backend-development-plan.md` §7 后才实施迁移。

```text
[现有] merchants
[现有] conversations
[现有] messages
[现有] answers                    # 含 client_request_id 幂等唯一约束
[现有] feedback
[现有] export_files
[现有] audit_logs                 # 越权访问与管理员操作
[现有] llm_usage                  # 调用次数与 token；purpose 区分 AGENT/LOCALIZATION
[现有] metric_definitions         # 含 metric_code 与 display_name
[现有] knowledge_documents
[现有] orders / order_items / refunds / returns / products / support_tickets
[现有] merchant_memories
[现有] chatbi_qa_daily
[现有] machine_translation_cache  # 按 merchant_id/GLOBAL 隔离，30 天过期
[现有] resource_localizations     # 按资源 ID/字段/源版本隔离
[现有] agent_sessions / conversation_provenance          # 会话计划 Task 2、6（迁移 0025、0026），已实现，待 Astra 审查
[N1 计划] products / orders / order_items 扩列           # 数据计划 M1、M2；orders.order_status 保留为派生兼容列，历史行回填
[N1 计划] inventory_events / fulfillment_events / after_sale_events   # M3，追加写；含历史订单回填事件
[N1 计划] drafts / change_ledger                         # M4
[N1 计划] coupons / guardrail_configs                    # M5
[N1 计划] customer_memories / merchant_memory_facts / merchant_memory_summaries / customer_signals / daily_briefs   # M6
[N1 计划] after_sales / after_sale_lines；refunds / returns / support_tickets 加 after_sale_id   # M7
[N1 计划] idempotency_records                            # M8，v2 幂等五元组唯一域（契约 §8.7.3）
[N4 计划] 索引版本与 pgvector 表
```

附件表与真实账号密码用户表均不在当前范围。N1 会话表只承载演示顾客/商家会话与不可变角色边界，
不应被扩写成 SSO 用户体系。

---

## 七、测试索引

### 后端

```text
backend/tests/unit/
backend/tests/integration/     # 需要真实 PostgreSQL，本机未启动 Docker 时会 skip
backend/tests/api/
backend/tests/support/         # 共享测试替身与 fixture
backend/tests/unit/tools/      # 工具注册表与闸门（tool_doubles.py：测试专用工具与内存端口）
backend/tests/unit/agent/loop/ # v2 主循环与上限（loop_doubles.py：脚本回合、慢工具、Reviewer 替身）
backend/tests/unit/skills/     # Skill 解析、路径逃逸、索引、冲突与受信通道（fixtures/ 两个测试用 Skill；skill_turns.py 组装带 Skill 的回合）
backend/tests/unit/services/v2/test_draft_dispatch.py      # 草稿分派表自检
backend/tests/integration/v2/test_draft_dispatch_db.py     # 分派经真实路由：处理器看不到证据、失败回滚证据、未注册种类 500
backend/tests/integration/tools/ # 闸门接真实来源状态与审计仓储
backend/tests/eval/baseline_comparison.py # N2 新循环与冻结基线结构对照（Fake LLM），生成 docs/history/eval/n2-baseline-comparison.md
backend/tests/postgres.py      # 集成测试的库连接辅助
```

Agent 流程测试不在独立的 `tests/agent/` 目录，而是分布在 `unit/` 与 `api/` 中。

重点覆盖：商家隔离；SQL 白名单和参数绑定；日期范围和行数限制；不同回答模式的路由；
指标口径命中与降级；Reviewer 重试上限；数据库不可用时的显式降级；
LLM 输出非法 JSON 时的处理；本地化级联与预算降级。

### 前端

```text
frontend/src/**/*.spec.ts       # Vitest 单测与 Adapter 契约测试
frontend/e2e/                   # Playwright Mock 套件（VITE_USE_MOCK=true）
frontend/e2e/real-api/          # 需要真实 v1 后端 + PostgreSQL，独立 playwright.real-api.config.ts
frontend/e2e/s3/、s4/、n3/      # 需要真实 v2 后端 + PostgreSQL + 脚本化模型（零 LLM 费用），各自独立 config
frontend/e2e/first-paint.spec.ts # 需要生产构建 preview，独立 playwright.first-paint.config.ts
```

重点覆盖：发送问题和连续追问；加载、错误和降级状态；图表切换；明细表和 CSV 下载；
采纳、点赞和点踩；桌面端与移动端布局；知识库权限；语言切换与持久化；
首屏静态依赖门禁。

**已知验证缺口（两页合并，2026-09-27）**：v1 前端页面下线后，`e2e/conversation.spec.ts`
（13 例，深度依赖 v1 Mock 传输层的细粒度 fixture 匹配）、`e2e/localization.spec.ts`（725 行，
依赖 v1 三栏 DOM 与 `chatStore.reloadForLocale()` 重放机制）、`e2e/real-api/analytics.spec.ts`
（8 例，验证 v1 后端指标/明细/导出/隔离能力，但通过已下线的 v1 前端页面驱动）已整份删除——
v2 层（`OpsAssistantView` 走裸 `fetch` 的 `/api/v2/merchant/*`）目前没有等价的 Mock 基础设施
支撑这类精细场景，重建这些验证需要先给 v2 层补一套类似 `mock/transport.ts` 的 fetch 拦截层，
超出两页合并本身的范围，留给后续专项处理。`e2e/assistant.spec.ts`、`isolation.spec.ts`、
`responsive.spec.ts`、`first-paint.spec.ts` 已改写为验证 v2 `OpsAssistantView` 的等价最小场景
（首屏可达、无控制台错误、导航齐全、商家/语言切换、响应式布局），用 `page.route` 直接 mock
`POST /api/v2/merchant/sessions`/`GET /api/v2/merchant/conversations` 两个端点。

**真实 LLM 不进入自动化测试**（`AGENTS.md` R3）。

---

## 八、规划文档目录分工

| 计划入口 | 当前用途 |
| --- | --- |
| `plans/2026-09-21-n1-module-roadmap.md` | **N1 总览**：模块 A–E 的划分、框架层、难度、依赖、出口标准与进度快照；不含实施步骤 |
| `plans/2026-09-22-n2-module-roadmap.md` | **N2 总览**：模块 0 与 A–F（工具循环、交易闭环、草稿与库存、会话目录与反馈、商家端 Vue 迁移、顾客端 Next.js）的划分、依赖、难度、出口标准与已知缺口；不含实施步骤 |
| `plans/2026-09-24-n3-module-roadmap.md` | **N3 总览**：阶段 0 与 A–C（A Skill 底座：加载器、`load_skill` 受信通道、草稿按种类分派；B 售后闭环与顾客 Skill，收口 S4；C 商家经营 Skill，收口 S2、S5、S6、S7）的划分、依赖、难度与出口标准；三份 N3 实施计划 `n3-skill-loader` / `n3-customer-skills-and-after-sales` / `n3-merchant-skills` 分别对应 A / B / C；不含实施步骤 |
| `plans/2026-09-27-n4-module-roadmap.md` | **N4 总览**：阶段 0 与 A–C（A 上下文与压缩，含多轮历史回放；B 双端记忆，含 outbox 异步管线与两端记忆界面；C 混合检索，含 pgvector 与索引原子切换）的划分、依赖、难度、费用点与出口标准；三份 N4 实施计划 `n4-context-compaction` / `n4-memory-pipeline` / `n4-hybrid-retrieval` 分别对应 A / B / C；待裁定 D-N4-1–D-N4-3；不含实施步骤 |
| `plans/2026-09-27-n5-module-roadmap.md` | **N5 总览**：阶段 0 与 A–D（A MCP 只读，收口 S8；B 预算、成本与可观测；C Cron 与 Railway 部署；D 全量评测与收口）的划分、依赖、费用与生产变更点、出口标准，及 N1–N5 路线完成定义；`n5-budget-ops-and-railway` 拆给 B（Task 1–3）与 C（Task 4–7）；待裁定 D-N5-1–D-N5-3；不含实施步骤 |
| `plans/2026-09-22-n2-assignment-and-review.md` | **N2 分工与 Astra 审查排期**（2026-09-22 已确认）：各模块实现模型（A、C Opus；B Sol；D、E Sonnet；F Codex Terra）、N2-1–N2-8 的证据要求与审查批次；不含实施步骤 |
| `plans/2026-09-24-n3-assignment-and-review.md` | **N3 分工与 Astra 审查排期**（2026-09-24 建立，待排期）：各阶段实现模型（A、C Opus；B Sol；前端补全 Sonnet + Terra，沿用各自在 N2 建立的地基）、N3-1–N3-5 的证据要求与审查批次；不含实施步骤 |
| `plans/2026-09-27-n4-assignment-and-review.md` | **N4 分工与 Astra 审查排期**（2026-09-27 拟定，待用户确认）：A Opus；B 后端 Sol、顾客记忆页 Terra、商家记忆面板 Sonnet；C Sonnet；N4-1–N4-4 的证据要求与审查批次；不含实施步骤 |
| `plans/2026-09-27-n5-assignment-and-review.md` | **N5 分工与 Astra 审查排期**（2026-09-27 拟定，待用户确认）：A Opus；B Sonnet；C Sol（生产操作逐项经用户同意）；D Task 1–6 Sonnet、Task 7–9 Opus；N5-1–N5-5 的证据要求与审查批次；不含实施步骤 |
| `plans/2026-09-20-n1-v2-contract-freeze.md` | N1 模块 A（v2 契约）实施计划，已完成 |
| `plans/2026-09-21-n1-llm-client-and-adapters.md` | N1 模块 B（LLM 客户端与双协议适配）实施计划 |
| `plans/2026-09-21-n1-data-migration-and-seeds.md` | N1 模块 C（数据迁移与确定性种子）实施计划 |
| `plans/2026-09-21-n1-session-identity.md` | N1 模块 D（会话身份与租户隔离）实施计划 |
| `plans/2026-09-21-n1-eval-harness.md` | N1 模块 E（评测骨架与安全硬门禁）实施计划 |
| `plans/2026-09-22-astra-checklist.md` | N1–N5 跨模块审查清单：由 Astra 审查的高风险点、证据要求与模型分工；不含实施步骤 |
| `plans/2026-09-16-agent-business-loop-upgrade.md` | 已登记状态，不定义当前范围 |
| `plans/2026-09-17-agent-business-loop-decisions.md` | 已登记状态，不定义当前范围；Q1/Q4 已失效，Q2/Q3 不阻塞 N1 |

| 目录 | 放什么 |
| --- | --- |
| `openspec/changes/` 与主 specs | OpenSpec change 的提案、设计、delta spec 与任务 |
| `docs/specs/` | 普通设计说明与规格（非 OpenSpec 流程） |
| `plans/` | 普通实施计划与整改计划 |
| `docs/superpowers/plans/`、`docs/superpowers/specs/` | 历史遗留：Superpowers 工作流产出的计划与设计，**保留不迁移** |

同一个需求只建一份主计划。已经在 `plans/` 或 `docs/specs/` 里的需求，不要再复制一套 Superpowers 计划；
已经在 `docs/superpowers/` 里的历史文档按需引用，新文档遵循上表约定。

N1 审查整改记录：`plans/2026-09-22-n1-review-remediation.md`。自动验证入口为
`.github/workflows/n1-checks.yml`（后端安全门禁、回归、独立时序任务及前端契约检查）；
工作流静态约束见 `backend/tests/unit/core/test_ci_contract.py`，评测零 skip 防回归见
`backend/tests/unit/test_eval_skip_gate.py`。关闭原因的存储/API 边界统一位于
`backend/app/domain/order_status_mapping.py`。
安全评测语言传递与真实错误响应验证见 `backend/tests/eval/test_security_locale.py`；
实际被测对象登记、阶段配额和端点分层的反向验证见 `backend/tests/eval/test_security_gate_guards.py`。

`plans/` **不是空目录**，当前有 51 份计划，其中 N1–N5 新路线实施计划 20 份（不含总览），另有 N1 总览 `2026-09-21-n1-module-roadmap.md`、N2 总览 `2026-09-22-n2-module-roadmap.md`、N3 总览 `2026-09-24-n3-module-roadmap.md`、N4 总览 `2026-09-27-n4-module-roadmap.md`、N5 总览 `2026-09-27-n5-module-roadmap.md`、N2 分工与审查排期 `2026-09-22-n2-assignment-and-review.md`、N3 分工与审查排期 `2026-09-24-n3-assignment-and-review.md`、N4 分工与审查排期 `2026-09-27-n4-assignment-and-review.md`、N5 分工与审查排期 `2026-09-27-n5-assignment-and-review.md` 各 1 份、
跨阶段审查清单 `2026-09-22-astra-checklist.md` 1 份；执行顺序与依赖见该总览与 `docs/project-progress.md` §四。其余为已完成或已登记状态的历史计划。开工前先查是否已有覆盖同一范围的计划。

---

## 九、历史建设顺序（已完成，仅供追溯）

MVP 从 0 到 1 按以下顺序建成。**这是历史记录，不是待办清单**；当前进度见 `docs/project-progress.md`。

1. 建立 `frontend/` 和 `backend/` 工程骨架；
2. 实现演示 Token 解析和 Merchant Context；
3. 定义 PostgreSQL 模型和 Alembic 迁移；
4. 建立商家隔离 Repository 基础设施，并写反例测试（跨商家访问必须 403 并写审计）；
5. 定义 Pydantic / OpenAPI 契约并生成 TypeScript 类型；
6. 迁移 Prototype UI，用 Mock API 打通完整前后端流程；
7. 实现知识检索和结构化意图；
8. 实现安全查询模板；
9. 实现回答、图表、建议和 Reviewer；
10. 实现基础限流、单请求 LLM 上限和每日预算熔断；
11. Docker 化并部署 Railway；
12. 旧 P1：日报、知识库后台、商家记忆、Chat BI、双语本地化已完成；附件当时未实现，后被新 PRD 延期；
13. 旧 P2：真实用户体系未实施，后被新 PRD 排除；
14. 数据规模证明 PostgreSQL 不够时，再评估 Doris。

其中两条**仍是现行上线门禁**，不因阶段完成而失效，见 `AGENTS.md` §二：

- 可信身份与商家隔离必须早于任何经营数据查询接口（R5）；
- 基础限流、单请求 LLM 上限和每日预算熔断必须早于把真实 LLM Key 部署到公开地址（R3）。

旧阶段拆分细节：后端见 `docs/backend-development-plan.md` §9，前端见
`docs/frontend-development-plan.md` §13。当前阶段只看 PRD §15 的 N1–N5。

---

## 十、维护本文件

出现以下情况更新本文件：创建或删除一级目录；移动关键入口文件；新增数据库或外部服务；
修改 Agent 节点顺序；`[规划]` 路径正式落地。

本文件是索引，不复制实现细节，也不定义接口字段。冲突时按 `AGENTS.md` 的文档权威关系判定。
