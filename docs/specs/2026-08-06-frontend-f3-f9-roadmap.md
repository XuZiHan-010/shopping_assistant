# 前端 F3–F9 路线图

## 目标

给出前端剩余七个阶段的依赖关系、跨阶段架构决策和契约缺口，让 F3–F6 的四对设计与实施计划有一个共同的裁决依据，避免同一决策在四份文档里各说各话。

本文件不是实施计划。F3–F6 的逐 Task 计划在 `plans/2026-08-06-frontend-f{3,4,5,6}-*.md`；F7–F9 因后端零契约，本文件只给前置条件，不写计划。

## 阶段依赖

```text
F3 Task 0（契约再生成）
  ├─→ F3 其余任务（真实传输层、错误码、401 恢复）
  ├─→ F4（图表、明细、导出）      依赖 F3 的 AppError 与 transport
  └─→ F5（质量轨迹、反馈、无障碍） 依赖 Task 0 重生的 Feedback* 类型
                                    ↓
                                   F6（Railway 与 MVP 收口）依赖 F4/F5 的 e2e 场景
                                    ↓
                          ─────── MVP 出口 ───────
                                    ↓
                    F7（附件与日报）← 后端 B8，尚未开工
                    F8（知识库后台）← 后端 B9，尚未开工
                    F9（内部可用版收尾）← F7/F8
```

F3 Task 0 是全局前置。不做这一步，F4 的导出和 F5 的反馈没有任何生成类型可用。

## 契约现状

### 已就绪（B0–B7 全部交付）

`POST /api/chat`（SSE 与 JSON 双路径）、`GET|DELETE /api/conversations[/{id}]`、`GET /api/demo/merchants`、`GET /api/metrics/{code}`、`POST /api/answers/{answer_id}/feedback`、`GET /api/exports/{export_id}`（签名 URL，不带鉴权头）、`GET /api/admin/ops/status`（`X-Admin-Token`，条件挂载，不出现在 OpenAPI 导出里）。

### 过期（F3 Task 0 的处理对象）

主目录 `docs/api.json` 与 `frontend/src/api/generated.ts` 缺 `/api/answers/{answer_id}/feedback`、`/api/exports/{export_id}` 两条路径与 `Feedback*` schema，`ErrorCode` 只有 10 个，缺 `EXPORT_LINK_EXPIRED`、`RATE_LIMITED`、`LLM_BUDGET_EXCEEDED`、`FORBIDDEN`。最新后端在 worktree `.worktrees/feature-b5-b6-answer-feedback-export/`。`ChatResponse` 本身两边一致，不受影响。

`npm run codegen:check` 当前是**通过**的——它只比对 `generated.ts` 与 `docs/api.json` 是否一致，防漂移但防不了源头过期。这是门禁盲区，不是门禁失效，Task 0 的失败判据因此只能是手工的。

`docs/fixtures/chat/detail-order.json` 有 `export` 对象，但 `url` 是 `/api/exports/{id}`，**没有 `?merchant_id=&expires_at=&signature=`**——它早于 B6 的导出服务。按此 fixture 开发导出入口，会写出一个对真实签名 URL 不成立的实现。Task 0 必须同时重跑 `scripts/export_chat_fixtures.py`。

### 缺失（F7/F8 的阻塞源）

附件、日报、知识库管理 CRUD 在后端零实现。详见本文末「F7–F9 前置条件」。

## 跨阶段架构决策

以下八条一旦分散到各阶段文档里就会互相打架，在此定死。各阶段计划引用本节编号，不重复论证。

### A1 · AppError 分层

协议层放 `src/api/errors.ts`，文案层放 `src/utils/errorCopy.ts`。

```ts
type AppErrorCode =
  | components['schemas']['ErrorCode']          // 后端 14 码
  | 'CONFIG' | 'NETWORK' | 'CANCELLED' | 'STREAM_INTERRUPTED' | 'CONTRACT'
```

`docs/frontend-development-plan.md` §4 目录树写的是 `src/utils/errors.ts`，本路线图改掉它：码集必须引用 `generated.ts`，放 `utils/` 会造出 `utils → api/generated` 的反向依赖，也让「`src/api/**` 不得 import `src/stores/**`」（见 A2）这条 ESLint 规则难以陈述。文案表反过来是纯 UI 策略，只 import 类型，放 `utils/` 正合适。

文案表用 `Record<AppErrorCode, ErrorCopy>` 而非 `Partial` + default 分支。后端新增错误码时 `codegen` 更新 `generated.ts`，typecheck **直接失败**，而不是静默落进 default——这是前端方案 §10 末尾「不要静默吞掉」的可执行版本。

`retryable` 以后端 `ErrorResponse.retryable` 为准，前端不自己判。前端判会在后端调整重试策略时静默不同步。

现有四个错误类改成 `AppError` 子类，不并存两套体系：`ApiConfigError` → `CONFIG`；`ChatStreamInterruptedError` → `STREAM_INTERRUPTED`（可重试）；`ChatContractError` → `CONTRACT`；`ChatStreamError` **删除**——它只保留了 `event.error.message`，把后端在流内给出的 `code` 和 `request_id` 丢掉了，导致 `LLM_BUDGET_EXCEEDED` 无法与普通 5xx 区分。

### A2 · Token 注入不产生 store↔api 循环

`src/api/credentials.ts` 做注册表，`main.ts` 在 `app.use(pinia)` 之后注入 provider，并显式把 pinia 实例传给 `useAuthStore`，这样单测不必构造应用外壳。

排除的两个方案：transport 内 `await import('@/stores/auth')` 能绕开静态循环，但把依赖藏起来，在没有 active pinia 的单测里炸得莫名其妙；token 逐层下传要改五个端点封装，漏一个就是一次 401，F7/F8 的接口还要再来一遍。

`TransportRequest` 现在就加 `auth?: 'merchant' | 'admin' | 'none'`（默认 `'merchant'`），这是前端方案 §6.2「两套凭证走两条独立的请求装配路径」的落点，不等 F8 再加。`/api/demo/merchants` 用 `'none'`；`/api/exports/*` 根本不走 transport（见 A5）。

用 ESLint `no-restricted-imports` 禁止 `src/api/**` import `@/stores/*`，把循环钉死，不靠代码评审。

请求 ID：每个请求生成 `crypto.randomUUID()` 塞 `X-Request-Id`。**后端 CORS 没有配 `expose_headers`，跨域下前端读不到响应头里的 `X-Request-Id`**，`requestId` 只能取自 `ErrorResponse.request_id`。不要设计「每次请求都展示请求编号」的 UI。

### A3 · 商家隔离改由 Token 决定

`resetTransportCache()` 从应用代码中消失。真实路径由服务端按 Token 过滤，本就不需要它；但 Playwright 强制 `VITE_USE_MOCK=true`，Mock 不实现同样语义，隔离 e2e 就是假绿。

Mock 传输层把会话表从 `Map<id, Conversation>` 改成 `Map<token, Map<id, Conversation>>`，key 取自收到的 `Authorization` 头。切换商家后什么都不用重建，Mock 与真实后端的隔离语义一致。

验收写成可 grep 的：`src/views/` 与 `src/components/` 下不得出现 `resetTransportCache` 标识符。

### A4 · 快速问题脱离 Mock

欢迎卡片的四个快速问题是产品文案，不是接口数据——后端没有 quick-questions 端点，`ChatResponse.suggestions` 只在回答之后才有。它们当初落在 `api/mock/scenarios.ts` 只是因为那儿正好有一份列表，这是位置错误而非数据来源错误。

移到 `src/constants/quickQuestions.ts`，依赖方向反转：`api/mock/scenarios.ts` 从该常量派生它的四个有 `category` 的场景。这样 Mock 能答的问题与欢迎卡片展示的问题永不漂移。

配套 ESLint `no-restricted-imports`：`src/**`（排除 `src/api/mock/**` 与 `**/*.spec.ts`）不得 import `@/api/mock/*`。

### A5 · 导出下载

`ExportInfo.url` 是相对路径且**已自带查询串**：`/api/exports/{id}?merchant_id=…&expires_at=…&signature=…`。前端只需前缀 API base。

`src/utils/download.ts` 的 `buildExportHref` 必须断言 `url` 以 `/api/exports/` 开头。这是唯一一处把服务端字符串直接放进 `href` 的地方，不校验就是一个开放重定向面。

**跨域时 `download` 属性会被浏览器忽略。** 生产环境后端是独立域名，能否真的触发下载完全取决于后端是否返回 `Content-Disposition: attachment`。F4 开工前先验证这一点。仍然写 `download` 属性（本地 dev 同源时有用），并加 `target="_blank" rel="noopener"`，这样万一后端返回 410 的 JSON，失败落在新标签页，不会冲掉 SPA 状态。

**410 的解法是不让它发生。** `ExportInfo.expiresAt` 前端已经有。渲染时算剩余 TTL：未过期显示「下载明细 CSV（链接 12 分钟后过期）」；已过期把 `<a>` 换成禁用态 + 「下载链接已过期，重新提问可生成新的导出」。历史回答、久置标签页两个真实场景全被这一步接住，不需要拦截任何东西——原生下载的状态码本来也拦不住。

**没有重签接口**，`export_id` 无法单独续期。前端方案 line 755「提供重新生成入口」不可实现，恢复动作是「重新提问」：用原用户问题重新 `submitMessage`，新的 `clientRequestId`。

### A6 · 指标面板不调 `GET /api/metrics/{code}`

`ChatResponse` 已带齐 7 个 `metric_*` 字段，再发一次请求得到的是同一份信息、不同的字段名（`display_name` vs `metric_display_name`）。代价却是真的：每个 METRIC 回答多一次请求、多一个 loading 态、多一个失败态、多一个 Adapter、多一份契约测试，还多一个「面板显示的口径和回答正文引用的口径来自两次读取」的竞态。收益为零。

该端点真正有用的场景是未来的指标词典页面与 `/metrics/{code}` 深链，届时才需要 `adapters/metric.ts` 做字段名映射。F4 不建 `api/metrics.ts` 与 `adapters/metric.ts`。

**「SQL 口径」的数据来源是 `query_plan.summary`**，不是 `metric_*`。PRD story 16 `[P0]` 要求「受控的 SQL 口径说明」，契约里对应的就是它。该字段已被 `adapters/chat.ts:186` 映射到 `ChatAnswer.data.queryPlan`，也已在 `types/chat.ts` 的领域模型里，只是至今没有任何组件渲染。F4 展示它，并明确标注为「查询计划摘要」——不得把业务口径伪装成 SQL 口径。

### A7 · ECharts 三层拆分

```text
src/utils/chart.ts             纯函数：validateChartRows / toChartOption / summarizeChart
src/composables/useEChart.ts   实例生命周期，模块级 echarts.use() 注册
src/components/insights/MetricChartPanel.vue   类型切换器 + a11y 降级块 + 容器 ref
```

`happy-dom` 没有 canvas，ECharts 真实渲染跑不了。所以纯函数层吃掉全部数据逻辑测试，组件测试 `vi.mock('echarts/core')` 只断言 init/setOption/dispose 的调用，真实渲染只在 Playwright 里断言 `<canvas>` 存在。

**按需引入放在 F4 而不是 F6。** 现在 `echarts` 装了但零 import，一旦有人写 `import * as echarts from 'echarts'`，产物直接多约 1MB，F6 再回头拆是返工，而且那时拆分会牵动所有 e2e 的加载时序。

实例存 composable 闭包的 `let` 里，**不用 `ref()`**——Vue 的深代理会污染 ECharts 内部状态；更不进 Pinia（前端方案 §6.1 明令）。`setOption` 恒带 `{ notMerge: true }`：BAR→PIE 合并会留下上一种图的 series 残骸。Resize 用 `ResizeObserver` 观察容器而非 `window.resize`——右侧栏宽度会因抽屉开合和断点变化而变，窗口尺寸不变。

后端把 Decimal 序列化成**字符串**、日期序列化成 ISO 字符串。`toNumber` 解析失败返回 `null`，**绝不返回 0**——0 是合法业务值，伪造 0 就是编造数据（AGENTS.md R7）。`null` 点在折线上留断口（`connectNulls: false`），数据表里显示 `—`。维度轴一律用 `category` 不用 `time`：后端已给出有序 ISO 字符串，改用 time 轴等于前端重建时区语义，是新增一个出错来源。

### A8 · 历史回放诚实降级

`GET /api/conversations/{id}` 只返回 `{id, role, content, created_at}`。图表、明细、导出、思考步骤、反馈状态全部不可恢复。

给 `ChatMessage` 加 `origin: 'live' | 'history'`，让降级说人话：

1. 侧栏在 `origin === 'history'` 时显示「历史会话仅保存回答正文，图表、明细与导出需重新提问获取」，而不是与「这轮回答本来就没有图表」长得一模一样的「暂无图表」。
2. **禁用历史消息的重试。** 现在 `loadConversation` 给每条历史消息发一个新的 `crypto.randomUUID()` 作 `clientRequestId`；对历史 assistant 消息点重试会拿前一条 user 文本发起一次**全新的真实计费请求**，而用户以为是「恢复」。
3. **不做「自动重问以补全」。** 静默重跑要花 token，还会把新答案挂在旧时间戳下——既违反 R3 的精神，也是在伪造历史。
4. 反馈按钮在历史消息上是否可用，取决于 `ConversationMessage.id` 是否等于 `answer_id`。**F5 Task 0 先读后端确认**，不能猜。
5. `stores/chat.ts` 现在假设「会话 id 就是 `/api/chat` 的 `session_id`」。F3 Task 5 必须验证；不成立的话，加载历史后追问会开一个新会话，而 UI 上看不出来。
6. `GET /api/conversations` 没有 `total`/`has_more`。**不造分页。** 固定 `limit=50`，列表底部写「仅显示最近 50 个会话」。

## 后端待办

以下五项前端无法自行解决，需后端配合。前四项影响 MVP 出口。

| # | 事项 | 影响 |
| --- | --- | --- |
| 1 | `chat.py::_sse_body` 改为增量推送 step | 现在 `await` 完整个 agent 再一次性回放全部 step，用户只看得到心跳。「1 秒内出现阶段标签」在真实后端**永远不达标**；F2 在 Mock 下的绿灯不可迁移，因为 Mock 是增量流的 |
| 2 | `/api/demo/merchants` 的开关与 `APP_ENV` 解耦 | `APP_ENV=production` 强制关闭该端点，生产环境商家切换器直接死掉，`auth.restore()` 拿不到 token，整条身份链断裂。建议改为显式 `ENABLE_DEMO_MERCHANTS` |
| 3 | `FRONTEND_ORIGIN` 支持多 Origin | 现在是单值、不支持逗号分隔、`*` 被拒。同一后端实例无法同时服务本地开发与生产前端，也无法服务 Railway 的 PR 预览域名 |
| 4 | 确认 `GET /api/exports/{id}` 返回 `Content-Disposition: attachment` | 跨域下 `download` 属性失效，能否触发下载完全取决于它 |
| 5 | 可选：导出链接重签接口；`GET /api/conversations/{id}` 返回结构化回答 | 分别解除 A5 与 A8 的降级 |

第 1、2 项在 F6 之前必须有结论。第 1 项没修，F3/F6 的对应验收标为 backend-blocked；第 2 项没修，MVP 出不了口。

## F7–F9 前置条件

### F7 · 附件与日报 ← 后端 B8

后端零实现：无 `attachments` 表与迁移、无 `POST|GET|DELETE /api/attachments`、无 worker/对象存储/OCR、无 `GET /api/reports/daily`、agent 图里没有附件节点。`ChatRequest.attachment_ids` 的 schema 是 `max_length=0`，传任何非空数组都会 422。

前端开工所需的最小后端契约：附件三个端点与 `AttachmentResponse`（含 `UPLOADING → PENDING → PARSING → PARSED | FAILED` 状态机）、解除 `attachment_ids` 长度限制、`ATTACHMENT` 模式的 agent 分支、`GET /api/reports/daily` 与其 `answer_id`（日报采纳复用现有反馈端点，不新增接口）。

### F8 · 知识库后台 ← 后端 B9

后端有 `knowledge_documents` 表、`KnowledgeRepository`、检索逻辑和 wiki 导入脚本，但**没有管理 CRUD 的 HTTP 面**：无 `GET /api/admin/knowledge/tree`、无 documents CRUD、无 ETag/乐观锁、无版本历史表。

前端开工所需的最小后端契约：知识树端点、文档 CRUD、ETag 或版本号的并发控制、团队知识与商家记忆的区分字段。

`src/api/credentials.ts` 的 `auth: 'admin'` 通道在 F3 就已建好并有测试，F8 不必重做凭证装配。

### F9 · 内部可用版收尾

无后端依赖，但依赖 F7/F8 交付完毕。内容为读屏完整走查、长会话虚拟列表评估与落地、大表渲染优化、P1 功能的独立 E2E。

## 边界

本路线图不改任何代码。`docs/api.json` 与 `src/api/generated.ts` 的再生成属于 F3 Task 0。

F7/F8 不写实施计划——对着不存在的后端契约凭空设计，后端 B8/B9 实际落地时大概率要重写。

P2 范围（真实 SSO、`/login`、令牌刷新、细粒度角色权限）不在本路线图内，也不得在 F3–F9 期间创建 `LoginView.vue`。
