# Borough 前端开发计划

> 适用对象：前端开发人员、全栈开发人员、coding agent  
> 产品名称：Borough 商家 AI 助手  
> 目标技术栈：Vue 3 + TypeScript + Vite  
> 产品范围：以 `docs/PRD.md` 为准  
> 工程规则：以根目录 `AGENTS.md` 为准

---

## 1. 开工前必读

按顺序读取：

1. `AGENTS.md`
2. `docs/PRD.md`
3. `yshopping-prototype/index.html`
4. `yshopping-prototype/styles.css`
5. `yshopping-prototype/app.js`
6. `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/App.vue`
7. `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/components/`
8. `yshopping-merchant-ai 4/yshopping-merchant-ai/frontend/src/api/client.js`

Prototype 是视觉和交互基准，旧 Vue 项目是业务字段和边界行为参考。新前端必须使用 TypeScript 重写，不直接复制旧 JavaScript 状态管理。

---

## 2. 前端目标

前端交付物必须做到：

- 桌面端 1:1 还原 Prototype 的三栏结构；
- 移动端变为对话优先的单列结构；
- 支持完整聊天、追问、附件、反馈和导出体验；
- 左右侧栏始终对应当前选中的助手回答；
- 所有 API 数据都有 TypeScript 类型；
- 错误、降级、数据来源和质量校验状态清晰可见；
- 可以先接 Mock API，再无痛切换 FastAPI；
- 通过组件测试、端到端测试和生产构建；
- 可作为 Railway 独立 Frontend Service 部署。

---

## 3. 技术选择

### 3.1 必需依赖

| 依赖 | 用途 |
| --- | --- |
| `vue` | UI 框架 |
| `typescript` | 类型系统 |
| `vite` | 开发与构建 |
| `vue-router` | 助手、知识库和登录路由 |
| `pinia` | 会话、认证和知识库状态 |
| `echarts` | 折线、柱状和饼图 |
| `@lucide/vue` | 图标。**不要用 `lucide-vue-next`**，上游已废弃（安装时会提示 `Package deprecated. Please use @lucide/vue instead`） |
| `zod` | 对关键运行时响应做防御性校验 |

### 3.2 开发依赖

| 依赖 | 用途 |
| --- | --- |
| `vitest` | 单元测试 |
| `@vue/test-utils` | Vue 组件测试 |
| `happy-dom` | 轻量测试环境 |
| `playwright` | 端到端和视觉验收 |
| `eslint` | 代码检查 |
| `prettier` | 格式化 |
| `openapi-typescript` | 从 FastAPI OpenAPI 生成 API 类型 |
| `@types/node` | `vite.config.ts` 用 `node:url`，`tsconfig.node.json` 声明 `types: ["node"]`，必须显式安装而非依赖传递 |

除非 PRD 或用户明确要求，不增加 UI 组件库。核心样式自主实现，以保持 Prototype 的视觉一致性。

---

## 4. 目标目录

```text
frontend/
├── Dockerfile
├── Caddyfile
├── package.json
├── package-lock.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── eslint.config.js
├── playwright.config.ts
├── index.html
├── scripts/
│   ├── check-generated.mjs        # generated.ts 漂移检查
│   ├── sync-fixtures.mjs          # fixture 镜像生成（F2）
│   ├── check-fixtures.mjs         # fixture 镜像漂移检查（F2）
│   └── check-no-mock-payload.mjs  # 生产产物不得含 fixture 载荷（F2）
├── public/
│   ├── borough-logo.svg
│   └── health.html
├── e2e/
│   ├── assistant.spec.ts
│   ├── responsive.spec.ts
│   ├── conversation.spec.ts
│   ├── attachments.spec.ts
│   └── knowledge.spec.ts
└── src/
    ├── main.ts
    ├── App.vue
    ├── api/
    │   ├── client.ts
    │   ├── generated.ts        # OpenAPI 生成，禁止手改
    │   ├── sse.ts              # fetch + ReadableStream 解析器
    │   ├── transport.ts        # Mock 与真实实现的唯一分叉点（F2）
    │   ├── mock/               # 仅 F2 演示数据；由动态 import 挡在生产之外
    │   │   ├── fixtures.generated.ts  # 由 npm run fixtures 生成，禁止手改
    │   │   ├── scenarios.ts
    │   │   └── transport.ts
    │   ├── adapters/           # 生成类型 → 领域模型的唯一转换点
    │   │   ├── chat.ts
    │   │   ├── metric.ts
    │   │   └── knowledge.ts
    │   ├── chat.ts
    │   ├── attachments.ts
    │   └── knowledge.ts
    ├── assets/
    │   ├── tokens.css
    │   ├── base.css
    │   └── styles.css
    ├── components/
    │   ├── common/
    │   ├── chat/               # ConversationColumn / ChatMessage / ChatComposer / ConversationNav
    │   ├── layout/             # MerchantSwitcher / ConversationDrawer
    │   ├── insights/           # MetricDefinitionPanel / MetricChartPanel / RecommendationPanel
    │   └── knowledge/
    ├── composables/
    │   ├── useChat.ts
    │   ├── useAutoScroll.ts
    │   ├── useFileUpload.ts
    │   └── useResponsiveLayout.ts
    ├── router/
    │   └── index.ts
    ├── stores/
    │   ├── auth.ts
    │   ├── chat.ts
    │   └── knowledge.ts
    ├── types/
    │   ├── chat.ts
    │   ├── insights.ts
    │   ├── attachments.ts
    │   └── knowledge.ts
    ├── utils/
    │   ├── format.ts
    │   ├── download.ts
    │   └── errors.ts
    └── views/
        ├── AssistantView.vue
        └── KnowledgeBaseView.vue
```

MVP 没有登录页——商家身份来自演示 Token 白名单，切换由顶栏的 `MerchantSwitcher.vue` 完成。P2 接入真实 SSO 时再增加登录视图。

不要一次创建所有空文件。按阶段创建真实需要的文件，并在目录或职责变化时更新 `AGENTS.md`。

---

## 5. 核心前端模型

### 5.0 类型分层与 Adapter 边界

后端是扁平 snake_case（`answer_mode`、`metric_code`、`data_rows`），前端领域模型是 camelCase。**转换必须发生在一个明确的地方**，否则会出现"OpenAPI 生成类型和手写类型并存、组件读到不存在的字段、Mock 能跑但真实 API 接入时集中报错"。

单向数据流，**组件不得直接消费 `generated.ts`，也不得自行转换字段**：

```text
后端 OpenAPI
   ↓ 代码生成（openapi-typescript）
src/api/generated.ts        禁止手改
   ↓ 唯一转换点
src/api/adapters/*.ts       每个 Adapter 配契约测试
   ↓
src/types/*.ts              本节定义的领域模型
   ↓
Pinia Store → 组件
```

规则：

- 每个 Adapter 有对应的 `*.spec.ts` 契约测试，用后端 OpenAPI 的示例载荷作为输入；
- 后端字段变化时，只有 `generated.ts` 和 Adapter 需要改，契约测试立刻暴露不兼容；
- Adapter 负责按模式判空：`METRIC` 以外的模式没有 `metric_*`，转换结果里对应字段就是 `undefined`，不要伪造默认值；
- **Mock 数据必须构造成 `generated.ts` 的类型再过 Adapter**，不允许直接手写领域模型当 Mock——那样等于绕过契约。

下面是前端需要稳定维护的领域模型。**字段的最终来源是 `docs/backend-development-plan.md` §8 和据此生成的 OpenAPI**，本节只描述前端形态。

### 5.1 回答模式

```ts
type AnswerMode =
  | 'METRIC'      // P0
  | 'DETAIL'      // P0
  | 'RULE'        // P0
  | 'IDENTITY'    // P0
  | 'CHAT'        // P0
  | 'INVALID'     // P0
  | 'ATTACHMENT'  // P1
```

`INVALID` 只表示"危险请求"或"无法处理"，是正常的 200 回答，要进消息列表并可反馈。**越权不走这个模式**——后端返回 HTTP `403`，前端按权限错误提示，不当作一轮回答。

响应字段分为"始终必填"和"按模式必填"两组，不适用的模式下按模式字段可能缺省或为 `null`。渲染前必须按 `mode` 判断，不能假设 `metric`、`dataRows`、`visualization`、`recommendations`、`export` 一定存在。

### 5.2 消息

```ts
type MessageStatus =
  | 'pending'     // 已入列，未发出或等待响应头
  | 'streaming'   // 正在接收 SSE
  | 'complete'    // 收到 done
  | 'cancelled'   // 用户主动取消
  | 'error'       // 失败，可重试

interface ChatMessage {
  localId: string
  id?: string
  clientRequestId: string        // 幂等键，随请求发送，见 §5.9
  role: 'user' | 'assistant'
  text: string
  createdAt: string
  status: MessageStatus
  attachments: AttachmentSummary[]
  response?: ChatResponse
}
```

`clientRequestId` 在消息**入列时**生成并常驻，不是发请求时才临时算——重试路径必须能从消息对象直接拿到它。

`cancelled` 与 `error` 分开是有意的：用户主动 `AbortController.abort()` 不是故障，UI 文案、是否自动提示重试、是否上报都不同。把取消混进 `error` 会让用户每次取消都看到一次"出错了"。

### 5.3 图表

```ts
interface Visualization {
  enabled: boolean
  type: 'line' | 'bar' | 'pie'
  allowedTypes: Array<'line' | 'bar' | 'pie'>
  title: string
  dimensionKey: string
  metricKey: string
  unit: string
  data: Array<Record<string, string | number | null>>
}
```

### 5.4 建议

```ts
interface Recommendation {
  title: string
  evidence: string
  action: string
}
```

### 5.5 质量状态

```ts
type AnalysisSource =
  | 'DATABASE' | 'KNOWLEDGE' | 'ATTACHMENT' | 'MEMORY' | 'FALLBACK' | 'NONE'

interface QualityTrace {
  status: 'PASSED' | 'DEGRADED' | 'FAILED' | 'NOT_RUN'
  attempts: number          // 0–2
  notes: string[]           // ← quality_notes，后端也是数组，无备注时为 []
  analysisSources: AnalysisSource[]   // 有序，主要来源在前，至少一项
  degraded: boolean
  degradedReason?: string
}
```

`notes` 与后端 `quality_notes` 同为字符串数组，无备注时是空数组而非 `null`，Adapter 不需要做 `null → []` 的兜底转换。

**没有 `RETRIED`。** 状态只表达最终质量结果，重试由 `attempts` 表达：重试后通过是 `PASSED` + `attempts=2`，重试后失败是 `FAILED` + `attempts=2`。UI 上"重试后通过"显示为通过并附一行"经过 2 次校验"，不单列一种状态。

**`analysisSources` 是数组不是单值**，因为一次回答常常同时用了数据库和指标知识。UI 渲染多个来源徽标，按数组顺序展示。含 `FALLBACK` 时 `degraded` 必为 `true`。

**`NONE` 是"本来就没有分析来源"**，用于 `CHAT` 问候闲聊和 `INVALID` 危险请求／无法处理。它只会单独出现，且 `degraded` 为 `false`。UI 对 `["NONE"]` **不渲染任何来源徽标**，也不显示降级提示——这类回答本来就不该有数据出处，硬贴一个徽标是在编造。

### 5.5.1 R9 历史轮次与纯明细表现

运行中只显示当前步骤标签；完成态按接收顺序列出全部步骤。历史助手消息从会话详情的脱敏
`answer_payload` 组装 `ChatAnswer`，因此也展示同一份完整步骤、质量轨迹和可信的当前反馈状态。
历史载荷没有完整明细行时，表格区展示列数、总行数、截断状态和“历史明细未保留，重新提问可查看完整数据”，
不得渲染空白助手消息或过期导出链接。详情契约不保存 `analysis_sources`，历史质量轨迹不得伪造来源标签；
只有 `answer_id` 与反馈状态同时存在时才开放历史反馈操作。

纯明细的 `answer` 是空字符串，组件只渲染表格与元数据；不得因为空正文而把它当作错误、加载中或历史空消息。
只有 `answer_id`、`is_adopted` 和 `reaction` 同时来自服务端时，历史消息才开放反馈操作。

### 5.6 指标口径

```ts
interface MetricDefinition {
  metricCode: string        // 稳定英文标识，接口路径和内部引用都用它
  displayName: string       // 中文展示名，只用于展示
  unit: string
  businessDefinition: string          // 由 OpenAPI Adapter 映射的业务口径，必填
  sqlDefinition?: string              // 由 OpenAPI Adapter 映射的 SQL 口径，可缺失
  dimensions?: string[]               // ← metric_dimensions，可缺失
  databaseName?: string               // ← metric_database_name，可缺失
  tableName?: string                  // ← metric_table_name，可缺失
  reportUrl?: string                  // ← metric_report_url，可缺失
  source: MetricDefinitionSource      // ← metric_source
  generated: boolean                  // ← metric_generated
  notice?: string                     // ← metric_notice，generated 为 true 时必有
  owner: string                       // ← metric_owner
  status: 'ACTIVE' | 'DEPRECATED' | 'UNVERIFIED'   // ← metric_status
}

type MetricDefinitionSource = 'METRIC_CATALOG' | 'COLUMN_COMMENT' | 'AI_GENERATED'
```

口径接口是 `GET /api/metrics/{code}`，路径参数用 `metricCode` 而非中文名。

**业务口径与 SQL 口径是两个并列字段。** 面向读者不同：业务口径回答"这个数是什么意思"，SQL 口径回答"这个数怎么算出来的"（PRD §6.3 故事 15/16）。前端不得把两者合并成一个"定义"分区。

**`source` 是枚举，不是自由文本。** 前端负责把它映射成人类可读标签（`METRIC_CATALOG` → "指标目录"、`COLUMN_COMMENT` → "字段注释"、`AI_GENERATED` → "大模型生成"），并渲染成来源徽标。**不要直接把枚举值原样打印给用户。**

**待核验告警由 `generated` 驱动，不是由 `status` 反推。** `generated` 为 `true` 时渲染醒目告警块并显示后端返回的 `notice` 文案；`notice` 是后端可配文案，前端不写死。`status === 'UNVERIFIED'` 是指标目录里的独立状态维度，两者都可能出现，互不替代。

**可选字段缺失时隐藏对应分区，不渲染空白占位。** `sqlDefinition`、`dimensions`、`databaseName`、`tableName`、`reportUrl` 都允许缺失。`reportUrl` 额外要求：只有通过 `^https?://` 校验才渲染链接，否则当作没有——防止后端或模型给出 `javascript:` 一类的伪协议。

### 5.7 推荐问题

```ts
interface SuggestedQuestions {
  current: string[]        // 当前展示的一组
  alternates: string[][]   // 其余候选组，"换一换"在本地轮换
}
```

推荐问题由后端从预置配置返回，**不是模型生成的**。"换一换"在 `alternates` 内本地循环，不发请求。

### 5.8 SSE 事件

```ts
type ChatStreamEvent =
  | { type: 'step'; label: string; node: string }
  | { type: 'done'; response: ChatResponse }
  | { type: 'error'; error: ApiError }
```

**`type` 来自 SSE 的 `event:` 字段，不是 `data` JSON 里的属性。** 后端在 `event:` 行给出事件名，`data` 只放载荷。解析器读 `event:` 并构造上面的 union，两处都写会不一致。

### 5.9 幂等标识

每条待发送消息持有一个 `clientRequestId`，随请求发送，后端据此保证不重复计费（后端 §8.5）。生成与复用规则：

| 场景 | 行为 |
| --- | --- |
| 首次发送 | 生成新 `clientRequestId` |
| 网络失败后重试 | **复用原 ID** |
| 用户修改问题后发送 | 生成新 ID |
| 用户主动"重新生成" | 生成新 ID，并记录来源回答 ID |
| SSE 流中断后恢复 | 复用原 ID，后端返回已完成结果或告知仍在处理 |

`ChatMessage` 中保存该 ID，重试路径必须能拿到它。

这些手写领域类型通过 Adapter 从 OpenAPI 生成类型转换而来，不得与后端协议产生重复且不一致的定义。

---

## 6. Pinia 状态设计

### 6.1 Chat Store

`frontend/src/stores/chat.ts` 负责：

- 当前会话 ID；
- 消息列表；
- 当前选中轮次；
- 当前输入和待上传附件；
- 加载、取消和重试状态；
- **SSE 流式状态**：已到达的 `step` 事件列表、当前阶段标签；
- 会话目录；
- 当前指标口径、图表、建议和推荐问题（含 `alternates` 与当前轮换下标）；
- 乐观反馈状态；
- 新会话、删除会话和历史会话加载。

### SSE 传输实现

**不能使用原生 `EventSource`。** 聊天请求同时需要 POST、JSON 请求体和 `Authorization` 头，`EventSource` 三者都不支持。实现方式固定为：

```text
fetch(url, { method: 'POST', headers, body, signal })
  → response.body.getReader()        ReadableStream
  → TextDecoder('utf-8', { stream: true })
  → 增量 SSE parser（src/api/sse.ts）
  → ChatStreamEvent
AbortController 负责取消
```

解析器必须处理的情况：

- **一次 `read()` 不等于一个完整事件**：可能读到半个事件，也可能一次读到多个事件。用缓冲区累积，按空行 `\n\n` 切分；
- **UTF-8 跨块字符**：必须用 `TextDecoder` 的 `{ stream: true }`，不能对每个 chunk 单独解码，否则中文会在块边界变成乱码；
- **心跳与空事件**：以 `:` 开头的注释行（如 `: keep-alive`）直接丢弃，不当作业务事件；
- **事件类型取自 `event:` 行**，`data:` 只做 JSON 解析；
- **HTTP 错误与流内错误分开**：响应头阶段的非 2xx（401/403/422/429）走普通错误路径，不进流；进入流之后的失败只会是 `event: error`。

### SSE 消费规则

- `step` 事件到达即追加并更新当前阶段标签，这是"1 秒内进入可见处理状态"的落点，**不使用本地假进度**；
- `done` 事件的载荷就是完整 `ChatResponse`，与非流式响应完全一致，**只写一套解析逻辑**（同一个 Adapter）；
- `error` 事件终止本轮并置为可重试；
- 流意外中断（既没有 `done` 也没有 `error`）视为错误，不能让消息永久停在 `streaming`；重试时复用原 `clientRequestId`，后端可能直接返回已完成结果；
- `cancelMessage` 调用 `AbortController.abort()` 中断底层流，不能只在 UI 上隐藏。取消后消息置为可重试状态，并提示"已取消"；
- 代理或网络中断与用户主动取消要区分展示：前者可重试，后者是用户意图。

不得把 DOM、ECharts 实例或原始 File 对象长期存入 Store。原始 File 保留在上传 composable 中，Store 只保存上传状态和服务端附件 ID。

建议动作：

```text
startNewConversation
loadConversation
submitMessage
retryMessage
cancelMessage
selectRound
applyFeedback
setPendingAttachment
removePendingAttachment
```

### 6.2 Auth Store

负责：

- 演示商家列表（来自 `GET /api/demo/merchants`）；
- 当前选中的演示商家及其 Token；
- 当前商家展示信息；
- 管理员权限（P1，独立的管理员令牌）；
- 切换商家与刷新。

**MVP 没有用户概念**，只有商家。不做登录页、不存密码，身份来自演示 Token 白名单。

Token 只放在内存与请求头 `Authorization: Bearer <token>`，**不写入 localStorage、URL、日志或前端构建产物**。

#### 刷新后如何恢复

Token 只存内存意味着刷新后会丢失，但产品要求刷新后能恢复会话。解法是**只持久化非敏感的商家标识，不持久化凭证**：

```text
sessionStorage: selected_demo_merchant_key   ← 非敏感标识，如 "merchant-100"
```

刷新后的顺序：

1. 重新调用 `GET /api/demo/merchants`；
2. 用 `selected_demo_merchant_key` 在返回列表中选回同一商家；
3. Token 从该响应取得，**仍然只进内存**；
4. 再加载该商家的会话列表与最近会话。

若标识在列表中找不到（演示商家配置变了或接口已关闭），回退到默认商家并提示重新选择。真实认证上线后（P2）重新设计持久化方式。

#### 401 的处理

**MVP 没有登录页，401 不能跳转 `/login`。** 正确行为：

- 清理内存中的失效 Token 和 `sessionStorage` 标识；
- 打开商家切换器；
- 提示"演示身份已失效，请重新选择商家"；
- **保留用户已输入但未发送的内容**，不清空输入框。

切换商家的语义是**更换请求携带的 Token**，商家身份仍由服务端解析决定。前端不得把 `merchant_id` 作为查询参数或请求体字段传给后端——即使传了后端也会忽略。切换后必须清空当前会话与侧栏，避免跨商家串数据。

#### 管理员 Token（P1）

知识库后台需要 `ADMIN_TOKEN`，它比演示 Token 敏感得多。**禁止**写入前端构建变量、硬编码、放进 URL，或保存在 `localStorage`。

存储与传输**已定死，不再二选一**：

| 项 | 取值 |
| --- | --- |
| 存储位置 | **`sessionStorage`**，键名 `admin_token` |
| 请求头 | **`X-Admin-Token: <token>`**，不复用 `Authorization` |
| 生命周期 | 标签页关闭即失效；同标签页刷新后仍有效，无需重输 |
| 清除方式 | 显式"清除授权"按钮；收到 401/403 自动清除 |

选 `sessionStorage` 而非纯内存，是因为管理员编辑长文档时误刷新会丢失授权、被迫重新输入令牌，而输入频率越高越容易被诱导粘贴到错误的地方。`sessionStorage` 的作用域是单标签页、关闭即清，风险可接受。

- 进入知识库页面时，若 `sessionStorage` 无令牌则弹出授权对话框，由管理员手动输入；
- **两套凭证走两条独立的请求装配路径**：商家接口只加 `Authorization`，管理员接口只加 `X-Admin-Token`，`api/client.ts` 里按接口分组决定，不做"有什么加什么"；
- 管理员令牌绝不出现在商家接口的请求上，反之亦然；
- 收到 401/403 时立即清除并重新要求输入。

路由守卫 `AdminTokenGuard` **只改善体验，不构成权限证明**。进入知识库页面时必须调用一个后端受保护接口验证权限，且所有写操作由后端独立校验——前端状态永远不是授权依据。

### 6.3 Knowledge Store

负责：

- 知识目录；
- 当前文档；
- 版本或 ETag；
- 未保存状态；
- 加载和冲突状态；
- 新建、保存、删除和刷新。

---

## 7. 开发阶段

## F0 · 工程骨架

### 任务

- [ ] 创建 Vue 3 + TypeScript + Vite 工程；
- [ ] 安装 Router、Pinia、ECharts 和 Lucide；
- [ ] 配置 `@/` 路径别名；
- [ ] 配置 ESLint、Prettier、Vitest 和 Playwright；
- [ ] `package.json` 的 `name` 设为 **`@borough/web`**（`AGENTS.md` 品牌约定）；
- [ ] 创建 `/` 路由；`/knowledge-base` 在 F0 只注册**空占位路由**（页面实现属于 P1 的 F8），这样 Router 配置一次成型不必回头改。**不创建 `/login`**——MVP 与 P1 都没有登录页，它属于 P2；
- [ ] **接入后端提交的 OpenAPI Schema，生成 `src/api/generated.ts`**，并搭好 `src/api/adapters/` 与首个契约测试；
- [ ] 创建 API 基础 URL 环境变量；
- [ ] 增加 `.env.example`，不得放真实值；
- [ ] 增加基础错误边界或全局错误提示；
- [ ] 创建 Frontend Dockerfile；
- [ ] 添加 `/health.html` 或等效静态健康响应。

### 必须存在的脚本

```json
{
  "dev": "vite",
  "build": "vue-tsc -b && vite build",
  "test": "vitest run",
  "test:e2e": "playwright test",
  "lint": "eslint .",
  "format:check": "prettier --check .",
  "codegen": "openapi-typescript ../docs/api.json -o src/api/generated.ts",
  "codegen:check": "node scripts/check-generated.mjs"
}
```

`src/api/generated.ts` **提交进版本库**：Railway 的 frontend Root Directory 是 `/frontend`，
镜像构建上下文里没有 `docs/`，构建期跑不了 `codegen`。代价是它可能与 `docs/api.json` 脱节
且不会有任何东西自动失败，所以 `codegen:check` 必须进本地门禁和 CI（但不进 Docker 构建）。

### 验收

- `npm ci` 成功；
- `npm run dev` 可以打开 `/`，`/knowledge-base` 返回占位页不报错，**不存在 `/login`**；
- `package.json` 的 `name` 为 `@borough/web`；
- `npm run build` 成功；
- `npm run test` 有至少一个真实测试；
- **`src/api/generated.ts` 由 OpenAPI 生成且未手改**，至少一个 Adapter 契约测试通过；
- `npm run codegen:check` 通过（手改 `generated.ts` 后必须失败）；
- 无 TypeScript 错误；
- Docker 镜像可以提供静态页面。

**Adapter 契约测试消费后端导出的真实载荷**（`docs/fixtures/chat/`，由
`scripts/export_chat_fixtures.py` 从 `FakeAgent` 导出），不由前端按生成类型自造。
类型只保证字段名、保证不了语义组合——自造载荷可以合法造出
`answer_mode="CHAT"` 配 `analysis_sources=["DATABASE"]` 这类后端永不产生的组合，
测试照样绿，等于自己批改自己的作业。

**OpenAPI 必须先于 Mock。** 后端在 B2 提交无实现的 Chat Schema，前端在本阶段就生成类型，F2 的 Mock 基于生成类型构造。顺序反过来会先形成一套本地字段，接入真实 API 时集中返工。

---

## F1 · 视觉基础与主布局

### 任务

- [ ] 从 Prototype 迁移颜色、间距、圆角、阴影和字体变量；
- [ ] 把变量拆到 `tokens.css`，基础规则放到 `base.css`；
- [ ] **使用或创建 `frontend/public/borough-logo.svg`，不得直接复制 Prototype 的 `yshopping-logo.svg`**——那是旧品牌资产，参考项目保留旧 IP 是正确状态，新工程不得残留；
- [ ] 实现 `AssistantView.vue` 三栏结构；
- [ ] 实现顶部品牌、知识库和新会话按钮；
- [ ] 实现 `MerchantSwitcher.vue`，按 560px 断点切换两种形态（见下）；
- [ ] 实现中间 Conversation Column；
- [ ] 实现左右侧栏容器；
- [ ] 实现桌面、窄桌面、平板和移动断点；
- [ ] 实现可见焦点、减少动画和空状态；
- [ ] 不使用 Prototype 的 `PROTOTYPE` 标记进入正式版本。

### 关键视觉基准

- 页面最大宽度约 1500px；
- 中间对话列最大宽度约 760px；
- 桌面侧栏约 230–280px；
- 页面背景使用轻量蓝绿色氛围渐变；
- 卡片使用浅色边框、低强度阴影和 9–18px 圆角；
- 移动端隐藏非必要标题，主对话高度可用；
- 页面级无横向滚动。

### 商家切换器（`MerchantSwitcher.vue`）

Prototype 中不存在此控件，它由演示 Token 方案引入，形态按 **Prototype 现有的 560px 断点**切换。PRD §13.1 是定稿依据。

| 视口 | 位置 | 形态 |
| --- | --- | --- |
| > 560px | 顶栏右侧操作区最左 | 独立按钮：状态圆点 + 商家名 + 箭头，高 36px、圆角 10px，与知识库/新会话同族 |
| ≤ 560px | 品牌标题下方副行 | 行内按钮：状态圆点 + 商家名 + 箭头，12px 字号 |

实现要点：

- **不引入新断点。** 560px 是 Prototype 已有的断点，同一档里 `.brand-title p` 被隐藏、`.new-chat-button` 收成图标；副行形态正是占用被隐藏的那行空位，所以不改动任何还原规则；
- **商家名在两个视口都必须可见**，不允许折叠成纯图标——这个控件的唯一用途是当场确认当前身份；
- 两种形态**共用同一个组件和同一份状态**，只切换渲染位置与样式，不写成两个组件；
- 下拉在窄屏要避免溢出视口，必要时左对齐并限制最大宽度；
- 副行形态的点击热区离 `h1` 很近，需保证足够高度，避免手机误触；
- 切换后调用 Chat Store 的重置，清空会话与侧栏。

已知最紧的一点是 **560px 刚上方**：此时新会话仍是带文字的全宽按钮，切换器也还在操作区，需实测该宽度不换行、不溢出。

### 验收

- 1440×1000 截图与 Prototype 主布局一致；
- 390×844 可以完整输入和发送；
- 360px 宽度无页面级横向滚动；
- 键盘 Tab 可以访问所有交互控件；
- `prefers-reduced-motion` 生效。

---

## F2 · Mock 会话闭环

### 组件

创建（本阶段结束时已全部存在）：

```text
components/chat/ConversationColumn.vue      # F1 创建，F2 接线
components/chat/ChatMessage.vue             # F2
components/chat/ChatComposer.vue            # F1 创建，F2 补自适应高度
components/chat/ConversationNav.vue         # F2
components/layout/MerchantSwitcher.vue      # F1 创建，F2 接 Auth Store
components/layout/ConversationDrawer.vue    # F2（历史会话抽屉，计划原文遗漏）
components/insights/MetricDefinitionPanel.vue
components/insights/MetricChartPanel.vue
components/insights/RecommendationPanel.vue
```

`DailyReportCard.vue` **不在本阶段创建**——日报是 P1，移到 F7。

### 任务

F2 已于 2026-08-04 收口。带阶段标注的条目是在更早的阶段就已交付、F2 只做接线或复用。

- [x] 基于 `generated.ts` 定义 `ChatMessage` 领域模型与 `api/adapters/chat.ts`；**（F0 已交付）**
- [x] 建立 Chat Store，消息持有 `clientRequestId`（见 §5.9）；
- [x] 建立 Auth Store，接入 `MerchantSwitcher.vue`（形态定稿见 F1）；**（切换器本身 F1 创建，F2 换掉硬编码商家名）**
- [x] 实现 `sessionStorage` 商家标识持久化与刷新恢复流程（见 §6.2）；
- [x] 实现欢迎卡片和一组快速问题（数量以 Prototype 为准）；
- [x] 实现用户消息和助手消息；
- [x] 实现 `src/api/sse.ts` 解析器与 SSE 消费、阶段标签展示；
- [x] 实现 pending、streaming、complete、error 和 cancelled 状态；
- [x] 实现输入框自适应高度；
- [x] 实现 Enter 发送和 Shift + Enter 换行；**（F1 已交付，含输入法组合态兼容）**
- [x] 实现自动滚动，但用户向上阅读时不强制抢滚动；
- [x] 实现当前轮次和对话目录；
- [x] 实现新会话重置与删除会话；
- [x] **Mock 构造成 `generated.ts` 类型后再过 Adapter**，不允许直接手写领域模型当 Mock；
- [x] 使用与 Prototype 一致的 mock 场景；
- [x] mock 结果必须明确标记为 mock（`analysisSources: ['FALLBACK']`），不能伪装真实数据库结果。

Mock 的边界：只有传输层是假的。载荷是后端 FakeAgent 的真实输出（`docs/fixtures/chat/` 的镜像），
`sse.ts`、`api/chat.ts`、Adapter 与两个 Store 走的都是真实代码路径。
`api/chat.ts` 已在 F2 建立，**F3 只替换 `api/transport.ts` 的实现与错误码分支，不要重新创建端点封装**。

### 验收

- 每个快速问题均可完成一轮问答；
- 切换器在 561px 与 559px 下分别渲染为按钮形态和副行形态，**两种形态都显示商家名**；
- 跨 560px 断点调整窗口时，当前选中商家不丢失；
- 560px 刚上方顶栏不换行、不溢出；
- 发送后 1 秒内出现阶段标签，且标签随 `step` 事件推进；
- 流中断时消息进入 error 而不是永久 streaming；
- 取消发送会真正中断底层请求；
- 切换商家后会话与侧栏清空；
- 连续发送两轮后目录包含两个节点；
- 点击目录可以跳到对应回答；
- 新会话清除当前消息和侧栏；
- 删除会话后目录与列表同步移除；
- 错误状态可重试；
- Store 测试覆盖发送、SSE 事件流、新会话、切换商家、选中轮次和错误恢复。

以上验收项已于 2026-08-04 全部通过：Vitest 109 passed / 15 files，Playwright 17 passed，
八条门禁（`lint`、`format:check`、`fixtures:check`、`codegen:check`、`mock:check`、`typecheck`、`test`、`build`）全绿。

---

## F3 · API 契约与真实会话接入

### 任务

- [ ] 建立统一 `api/client.ts`；
- [ ] 自动附加认证信息和 request ID；
- [ ] 区分 401、403、409、410、422、429 和 5xx；
- [ ] **重新生成** `api/generated.ts`（F0 已首次生成），并补齐 `api/adapters/` 各 Adapter 与契约测试；
- [ ] 创建 `api/chat.ts`；
- [ ] 实现会话列表和会话详情；
- [ ] 实现聊天提交，请求体携带 `client_request_id`；
- [ ] 实现请求取消；
- [ ] 保存后端返回的 `session_id`；
- [ ] 对关键响应做防御性解析：后端缺少按模式必填字段时降级展示而非崩溃；
- [ ] 后端协议错误显示友好错误，不让页面崩溃；
- [ ] API 地址只来自 `VITE_API_BASE_URL`。

### API 客户端规则

- 不在组件中直接 `fetch`；
- 不在日志打印访问令牌、附件正文或完整经营数据；
- 所有错误转换为统一 `AppError`；
- 超时和取消与服务器错误分开；
- **401 走"清 Token → 打开商家切换器 → 提示重新选择商家 → 保留未发送输入"**（见 §6.2），不跳登录页、不无限重试；
- 409 `REQUEST_IN_PROGRESS` 提示"正在处理中"，不重复提交；
- 429 显示稍后重试信息。

### 验收

- Mock Service 和真实 API 可以通过配置切换；
- 刷新页面后能重新选回同一商家并恢复会话，Token 不落 `localStorage`；
- 401 时不会跳转到不存在的 `/login`，且未发送内容仍在输入框；
- 同一会话追问携带正确会话 ID；
- 网络中断显示错误并允许重试，**重试复用原 `clientRequestId`**；
- Adapter 契约测试覆盖 **P0 六种模式全部载荷**：`METRIC`、`DETAIL`、`RULE`、`IDENTITY`、`CHAT`、`INVALID`（`ATTACHMENT` 随 F7 补第七条）；
- TypeScript 不使用 `any` 绕过接口问题。

---

## F4 · 指标、图表、明细和建议

### 4.1 Metric Definition

- [ ] 展示指标名称（`displayName`）；
- [ ] 展示业务口径（`businessDefinition`，必填，缺失时显示"暂未返回业务口径。"）；
- [ ] 展示 SQL 口径（`sqlDefinition`，缺失时**隐藏该分区**，不留空白占位）；
- [ ] 把 `source` 枚举映射成中文来源徽标（指标目录／字段注释／大模型生成），不原样打印枚举值；
- [ ] 展示 `owner`、`status` 与 `unit`；
- [ ] `generated` 为 `true` 时显示醒目告警块并渲染后端返回的 `notice` 文案；
- [ ] `status` 为 `UNVERIFIED` 时显示待核验提示（与 `generated` 告警是两条独立分支，可同时出现）；
- [ ] 展示来源库表（`databaseName` / `tableName`）与维度集合（`dimensions`），各自缺失即隐藏；
- [ ] 有 `reportUrl` 且通过 `^https?://` 校验时，展示"查看关联报表"外链（`target="_blank"` + `rel="noopener noreferrer"`）；
- [ ] 无口径时显示空状态。

版式与分区顺序对齐参考项目 `frontend/src/components/MetricDefinitionPanel.vue`（R9：参考项目是需求基准）。可选字段一律"有才渲染"，这是参考项目的既有行为，不是降级。

### 4.2 Chart

- [ ] 使用 ECharts 实现折线、柱状和饼图；
- [ ] 只允许后端返回的 `allowedTypes`；
- [ ] 使用后端指定的维度和指标字段；
- [ ] 无数据或字段缺失时显示解释，不抛异常；
- [ ] 金额、人数、订单和百分比分别格式化；
- [ ] 支持 tooltip 和键盘可访问的摘要；
- [ ] 图表销毁时释放 ECharts 实例；
- [ ] 容器变化时 resize。

**图表无障碍降级内容**（ECharts 本身无法让键盘和读屏用户理解数据，以下四项都要有）：

- 图表标题（说明这是什么的趋势或分布）；
- 汇总数字（总量、均值或占比）；
- 趋势文字描述（如"最近 30 天呈上升趋势，环比 +12%"）；
- 可访问的数据表或等价文本摘要，能用键盘到达；
- **颜色不能作为唯一编码**：折线用不同线型或标记点，饼图标注文字标签。

### 4.3 Detail Table

- [ ] 中文列名映射；
- [ ] 横向内部滚动；
- [ ] Sticky Header；
- [ ] 展示总数、预览数和截断说明；
- [ ] **CSV 下载用 `<a href={export.url} download>` 原生下载**，不用 `fetch` + Blob；
- [ ] 空值、金额、日期和布尔值统一格式化；
- [ ] 敏感字段尊重后端脱敏结果；
- [ ] 超宽 JSON 不破坏布局。

#### 导出下载为什么不走 fetch

`GET /api/exports/{id}` 的签名 URL **自带鉴权，不需要 `Authorization` 头**（后端 §8.0）。因此直接把 `response.export` 里的 URL 交给 `<a download>` 即可：浏览器原生下载，不占标签页内存，有下载进度。

- 不要为了"统一走 client.ts"而改成 `fetch` + `Blob` + `URL.createObjectURL`——那会把整个 CSV 读进内存；
- 签名有效期 15 分钟，过期后端返回 `410 EXPORT_LINK_EXPIRED`，前端提示并提供重新生成入口；
- 导出 URL 不写进日志、不放进可分享的位置。

### 4.4 Recommendations

- [ ] 至少展示标题、依据和行动；
- [ ] “猜你想问”可以直接发送；
- [ ] 换一换在响应携带的 `alternates` 内本地轮换，**不发额外请求**；
- [ ] `CHAT` 模式也展示推荐问题（入门问题组），这是新用户的功能发现入口；
- [ ] 回答切换后侧栏同步更新；
- [ ] 建议为空时显示明确空状态。

### 验收

- METRIC 回答完整展示口径、图表和建议；
- DETAIL 回答完整展示表格和导出；
- RULE 回答不显示虚构图表；
- 切换当前轮次时侧栏不会显示旧回答数据；
- 图表数据不能引用不存在的字段。

---

## F5 · 质量轨迹、反馈与无障碍基础

### 5.1 Quality Trace

- [x] 展示 `PASSED`、`DEGRADED`、`FAILED`、`NOT_RUN` 四种状态，**没有 `RETRIED`**；
- [x] 展示 Reviewer 尝试次数；"重试后通过"渲染为通过 + "经过 2 次校验"，不单列状态；
- [x] 展示可折叠备注（`quality_notes`）；
- [x] 展示 `analysisSources` 全部来源徽标，按数组顺序；
- [x] 降级状态不允许只放在 tooltip 中。

### 5.2 Feedback

- [x] 采纳、点赞和点踩；
- [x] 点赞与点踩互斥；
- [x] 乐观更新失败时保留本地反馈意图并显示错误；"已记录"只在服务端确认后显示；
- [x] 防止重复快速提交；失败后允许同一反馈重试；
- [x] 显示保存中与已记录状态。

### 5.3 无障碍基础（P0，不延后）

无障碍不是 P1 的收尾工作，基础要求在 MVP 就要满足：

- [x] 所有图标按钮有 `aria-label`；
- [x] 错误和加载状态使用 `aria-live`；
- [x] 对话新增内容可被辅助技术感知；
- [x] 表格有表头；
- [x] 图表有文本摘要（见 F4）；
- [x] 模态框管理焦点；
- [x] 颜色对比满足基本可读性，且颜色不是唯一编码；
- [x] 支持键盘关闭目录和弹窗。

### 验收

- 反馈失败保留本地反馈意图并给出可见提示，失败后可重试；"已记录"以服务端确认为准；
- 降级回答清晰可见，不只在 tooltip 里；
- 质量状态显示"重试后通过"时是 `PASSED` + 2 次，不出现 `RETRIED`；
- 多个分析来源能同时展示；
- 键盘可完成"提问 → 阅读回答 → 反馈"全流程。

---

## F6 · Railway 与 MVP 收口

**本阶段属于 P0，是前端 MVP 的最后一步。执行顺序是 F0 → F6，不要为了做 P1 功能推迟部署。**

### 网络拓扑

**方案已定：Backend 公开 + 严格 CORS**，浏览器直连后端公网地址，前端不做反向代理。

- [ ] `VITE_API_BASE_URL` 指向公开的 Backend 域名；
- [ ] 与后端确认 CORS 允许本前端的精确 Origin，允许头含 `Authorization`、`Accept`、`Content-Type`、`X-Request-Id`；
- [ ] 验证**真实 CORS 环境下 SSE 正常流式**，不是一次性返回；
- [ ] 前端容器只做静态托管，不引入 Caddy/Nginx 的 `/api` 代理规则。

### 部署

- [ ] Frontend Service Root `/frontend`；
- [x] 构建产物不包含任何密钥；`secrets:check` 递归扫描构建产物，且已用受控泄漏变异验证其会失败。
- [x] 静态健康响应可用；`public/health.html` 由 Caddy 独立处理，线上可用性留待 F6-B 验证。
- [x] 生产构建关闭 Mock 开关；`VITE_USE_MOCK=true` 会在 Vite 配置解析期失败，Dockerfile 也显式透传该构建变量。

### 性能

- [x] 路由级代码分割；`/knowledge-base` 保持 lazy，`/` 是首屏故意 eager。真正的首屏收益来自图表面板的显式挂载开关，而不是把助手入口延迟加载。
- [x] ECharts 按需引入；`chartMountable` 显式控制异步图表面板挂载。`e2e/first-paint.spec.ts` 的生产预览网络观测与 `firstpaint:check` 的静态依赖检查提供双层证据。
- [ ] 长会话评估虚拟列表，但 MVP 明确不做；已评估，不提前实现。
- [ ] 避免重复渲染完整大表；
- [x] 构建产物不包含源密钥；见上方 `secrets:check` 及其变异验证。

### 验收（MVP 出口）

**保持未勾选：依赖 F6-B 的 Railway 控制台部署与真实跨域验收。** F6-A 的本地构建、静态门禁和 Fake/确定性测试不能替代真实部署，也不构成「MVP 完成」声明。

- 通过 Railway 部署域名完成核心 E2E：提问 → 阅读回答 → 反馈 → 导出；
- SSE 在真实跨域环境下 1 秒内出现首个阶段标签；
- 刷新后能重新选回商家并恢复会话；
- 360px 和 1440px 视口均可用；
- **P0 E2E 不依赖附件、日报和知识库**。

---

## F7 · 附件与日报（P1）

**本阶段属于 P1，在 MVP 上线之后执行。**

### 7.1 Daily Report

- [ ] 创建 `components/chat/DailyReportCard.vue`；
- [ ] 展示日期、摘要和核心指标；
- [ ] 展示日报建议；
- [ ] **建议采纳复用回答反馈接口**：日报响应返回 `answer_id`，采纳时调用 `POST /api/answers/{id}/feedback`，不新增接口；
- [ ] 无日报时不阻塞主界面。

### 7.2 Attachments

- [ ] 文件选择；
- [ ] 拖拽上传；
- [ ] 粘贴图片；
- [ ] 数量、类型和大小前端预检查；
- [ ] 发送前移除；
- [ ] 聊天请求只发送服务端附件 ID；
- [ ] 离开页面前提示未发送附件；
- [ ] 前端检查只是体验优化，不能替代后端校验。

#### 附件状态机与轮询策略

后端状态枚举（后端 §9 B8）：`UPLOADING → PENDING → PARSING → PARSED`，失败进入 `FAILED`。前端据此实现统一状态机，**不要每个组件各写一套轮询**：

| 项 | 规则 |
| --- | --- |
| 轮询间隔 | 初始 1s，指数退避 ×1.5，上限 8s |
| 总超时 | 120s，超时后标记为"解析超时"并允许重试或移除 |
| 页面隐藏 | `visibilitychange` 为 hidden 时暂停轮询，恢复时立即拉一次 |
| 组件卸载 | 必须清理定时器，不允许泄漏 |
| 轮询方式 | **每个附件独立轮询 `GET /api/attachments/{id}`**，不新增批量接口 |
| 多附件并发 | 并发数上限 **3**，超出的排队 |
| 删除解析中的附件 | 先停止该附件轮询，再调用删除；后端返回 409 时提示"正在解析，请稍后" |
| 上传取消 | `AbortController` 中断上传请求，本地状态回到未上传 |

### 7.3 `ATTACHMENT` 模式渲染

- [ ] 附件分析回答与普通回答共用消息组件；
- [ ] `analysisSources` 含 `ATTACHMENT` 时展示附件来源徽标；
- [ ] 附件仍在解析时，回答明确显示"附件尚未解析完成"，不展示编造结论。

### 验收

- 上传非法类型会被拒绝；
- 上传成功后附件随消息展示；
- 附件解析失败不影响继续纯文本问答；
- 轮询在页面隐藏时暂停、组件卸载时清理，无定时器泄漏；
- 解析超时有明确出口，不无限转圈；
- 日报建议采纳能成功写入反馈。

---

## F8 · 知识库后台（P1）

### 页面结构

```text
KnowledgeBaseView
├── AdminTokenGuard
├── KnowledgeTree
├── DocumentEditor
├── VersionConflictDialog
└── Create/Delete Dialog
```

### 任务

- [ ] **管理员临时授权对话框**（见 §6.2）：手动输入、仅内存或 `sessionStorage`、提供清除按钮；
- [ ] 管理员路由守卫 `AdminTokenGuard`——**只改善体验，不构成权限证明**；
- [ ] 进入页面时调用后端受保护接口验证权限，401/403 立即清除令牌并重新要求输入；
- [ ] 左侧目录树；
- [ ] Markdown 编辑器；
- [ ] 读取、创建、保存和删除；
- [ ] 使用版本或 ETag 防止覆盖；
- [ ] 冲突时保留本地内容并提示重新加载；
- [ ] 明确区分团队知识和商家记忆；
- [ ] 商家记忆默认只读，**不能通过知识后台改写成团队事实**；
- [ ] 删除操作二次确认；
- [ ] 未配置管理员令牌时 fail closed。

### 验收

- 非管理员不能访问写接口；
- 管理员令牌不出现在 URL、构建产物和 `localStorage`；
- 刷新页面后需要重新授权；
- 清除授权按钮生效，之后写接口立即失败；
- 并发编辑产生可理解的冲突提示；
- 未保存内容不会静默丢失；
- 团队知识和商家记忆视觉上明确区分。

---

## F9 · 内部可用版收尾（P1）

- [ ] 无障碍增强：读屏完整走查、复杂控件的键盘操作、动效偏好；
- [ ] 性能：长会话虚拟列表评估与落地、大表渲染优化、图片预览释放 Object URL；
- [ ] P1 功能的独立 E2E（附件、日报、知识库各一组）；
- [ ] 内部可用版整体回归。

**P2 才做**：真实 SSO、登录页 `/login`、令牌刷新、细粒度角色权限。在此之前不要创建 `LoginView.vue`。

---

## 8. 测试与交付要求

### 8.1 单元和组件测试

必测：

- [ ] Chat Store；
- [ ] SSE 事件流消费：`step` 累积、`done` 收尾、`error` 终止、中断不停留在 streaming；
- [ ] 错误转换；
- [ ] 金额、日期和单元格格式化；
- [ ] Chat Composer 键盘行为；
- [ ] `MerchantSwitcher` **两种断点形态**：> 560px 按钮形态、≤ 560px 副行形态，两者都渲染商家名；
- [ ] `MerchantSwitcher` 跨断点时选中商家不丢失；
- [ ] 切换商家后 Chat Store 与侧栏被清空；
- [ ] Metric Definition 的生成口径警告（由 `generated` 驱动，渲染后端 `notice`）与 `metricCode` 展示；
- [ ] Metric Definition 的双口径渲染：业务口径必显示、`sqlDefinition` 缺失时整块隐藏；
- [ ] Metric Definition 的 `source` 枚举 → 中文徽标映射三种取值全覆盖；
- [ ] Metric Definition 的 `reportUrl` 协议校验：`https?` 渲染外链，其他协议一律不渲染；
- [ ] 推荐问题的"换一换"在 `alternates` 内本地轮换且不发请求；
- [ ] Quality Trace 的降级显示与 `analysisSources` 多来源渲染；
- [ ] Feedback 乐观更新和回滚；
- [ ] Attachment 状态机（P1）；
- [ ] 当前轮次切换；
- [ ] **Adapter 契约测试**：每个 Adapter 用 OpenAPI 示例载荷输入，P0 覆盖 `METRIC` / `DETAIL` / `RULE` / `IDENTITY` / `CHAT` / `INVALID` 六种模式，`IDENTITY` 不可遗漏（它有 `data_rows` 但无 `metric_*`，是最容易漏判的一种）；
- [ ] **SSE 解析器**：跨分块事件、半个 UTF-8 字符跨块、单块内多个事件、心跳注释行、`done` 之后无残留；
- [ ] **`clientRequestId`**：首发生成、网络重试复用、改问题后换新、主动重新生成换新；
- [ ] **刷新恢复**：`sessionStorage` 商家标识存在时重新选回商家并加载会话；标识失效时回退默认商家；
- [ ] **401 不跳转 `/login`**，且未发送输入被保留；
- [ ] **防御性解析**：后端缺少按模式必填字段时降级展示而非崩溃；
- [ ] 管理员 Token 输入、清除与权限失败（P1）。

### 8.2 Playwright

**所有 Playwright 测试默认使用 Fake LLM**，通过后端的 Fake Agent 或"真实 Graph + Fake LLM"提供数据。CI 和默认本地运行**都不得连接真实 DeepSeek API**。任何真实模型的人工验收必须事先说明模型、次数和费用并获得同意（`AGENTS.md` R3）。

E2E 按阶段分组，**MVP 出口只跑 P0 组**：

```text
e2e/p0/   assistant.spec.ts  responsive.spec.ts  isolation.spec.ts
e2e/p1/   attachments.spec.ts  daily-report.spec.ts  knowledge.spec.ts
```

P0 场景：

- [ ] 打开页面并完成 GMV 问答；
- [ ] 完成退货趋势并切换图表；
- [ ] 查看订单明细和下载入口；
- [ ] 查询商品规则；
- [ ] 连续追问并使用目录导航；
- [ ] 新会话与删除会话；
- [ ] 切换商家后数据不串：切到另一商家看不到上一商家的会话与数据；
- [ ] 刷新页面后仍是同一商家且会话可恢复；
- [ ] 采纳、点赞和点踩；
- [ ] 390×844 移动端（切换器为副行形态）；
- [ ] 1440×1000 桌面端（切换器为按钮形态）；
- [ ] 570×900 —— 560px 断点刚上方，顶栏最挤的一点，验证不换行不溢出；
- [ ] 后端 500 和降级回答；
- [ ] **真实部署环境下的 SSE 流式**（跨域 + 首字延迟）。

P1 场景：

- [ ] 上传、移除和发送附件；
- [ ] 附件解析轮询与超时；
- [ ] 日报展示与建议采纳；
- [ ] 知识库权限与版本冲突。

### 8.3 Railway

**网络拓扑：Backend 公开 + 严格 CORS。** 前端容器只做静态托管，不代理 `/api`。

- [ ] 生产构建输出静态文件；
- [ ] 使用 Caddy、Nginx 或等效静态服务器；
- [ ] SPA 路由回退到 `index.html`；
- [ ] `VITE_API_BASE_URL` 指向公开的 Backend 域名；
- [ ] Frontend 与 Backend 均有公开域名，Backend 侧配置精确 Origin 的 CORS；
- [ ] 验证健康地址；
- [ ] 验证移动端和桌面端真实部署；
- [ ] 验证跨域 SSE 不被缓冲，首个 `step` 在 1 秒内到达。

### 阶段完成条件

```powershell
npm run lint
npm run format:check
npm run test
npm run build
npm run test:e2e
```

全部通过，浏览器控制台无错误，核心页面没有横向溢出。

---

## 9. API 接入顺序

前端不得等待所有后端功能完成。**但 OpenAPI Schema 必须最先到位**——Mock 基于生成类型编写，不允许先自由定义字段再回头替换：

```text
后端提交无实现的 OpenAPI Schema（后端 B2）
  → 前端生成 api/generated.ts（F0）
  → 基于生成类型编写 Mock
  → 完成 F2 UI
  → 接入真实 API（F3）
```

协作顺序：

1. 后端先提供 OpenAPI Schema 和 Fake Chat；
2. 前端生成类型、搭 Adapter，完成消息和侧栏；
3. 后端提供指标和明细演示数据；
4. 前端完成图表、表格和建议；
5. 后端提供反馈和会话；
6. 前端完成恢复和反馈；
7. **双方各自完成 Railway 部署与 MVP 收口**（后端 B7 / 前端 F6）；
8. 后端提供附件与日报；
9. 前端完成附件状态与日报；
10. 后端提供知识库；
11. 前端完成知识后台。

Mock 字段与 OpenAPI 不一致时，以 OpenAPI 为准并修 Mock，不要反过来改契约。

---

## 10. 前端错误展示标准

| 场景 | 页面表现 |
| --- | --- |
| 网络断开 | 消息级错误，可重试（复用原 `clientRequestId`） |
| 401 | **清 Token 与商家标识 → 打开商家切换器 → 提示重新选择商家 → 保留未发送输入。不跳转 `/login`** |
| 403 `MERCHANT_SCOPE_VIOLATION` / `FORBIDDEN` | 明确无权限，不显示空数据，不当作一轮回答 |
| 404 `NOT_FOUND` | 资源不存在（会话已被删除、导出记录过期清理等）。提示并从本地列表移除该项，不要停在加载态 |
| 405 `METHOD_NOT_ALLOWED` | 前端调用方式错误，属于开发期缺陷，上报而非提示用户 |
| 409 `VERSION_CONFLICT` | 知识版本冲突，保留本地内容 |
| 409 `REQUEST_IN_PROGRESS` | 提示"正在处理中"，不重复提交 |
| 409 `IDEMPOTENCY_KEY_REUSED` | 内部错误，说明 ID 复用逻辑有 bug，上报而非提示用户重试 |
| 410 `EXPORT_LINK_EXPIRED` | 导出链接已过期，提供重新生成入口 |
| 413 | 文件过大 |
| 415 | 文件类型不支持 |
| 422 | 输入或协议错误 |
| 429 `RATE_LIMITED` | 请求过多，提示稍后重试 |
| 503 `LLM_BUDGET_EXCEEDED` | 明确提示"今日额度已用完"，与普通 5xx 区分 |
| 500 `INTERNAL_ERROR` | 服务暂不可用，保留用户输入 |
| 其他 4xx `HTTP_ERROR` | 通用错误兜底，保留用户输入并允许重试 |
| LLM 降级 | 正常卡片内明确展示降级状态，不只在 tooltip |
| 数据为空 | 解释为空，不显示错误图表 |

错误码全集见 `docs/backend-development-plan.md` §14，代码侧出处是 `app.core.errors.ErrorCode`。
**遇到表中没有的码时按通用错误展示并上报，不要静默吞掉**——静默会让新增的后端错误在前端彻底不可见。

---

## 11. 前端禁止事项

- 不在组件中直接拼 API URL；
- **不在组件中直接消费 `api/generated.ts`，也不在组件里自行做字段转换**——只走 Adapter；
- **不使用原生 `EventSource`** 消费聊天流；
- **不创建 `/login` 路由或 `LoginView.vue`**，直到 P2 真实认证；
- **不把 Token 写入 `localStorage`**，只有非敏感商家标识可进 `sessionStorage`；
- 不使用 `any` 掩盖接口问题；
- 不让模型返回 HTML 后直接 `v-html`；
- 不信任附件名称、Markdown 或外部链接；
- 不允许前端指定可信商家 ID，任何请求都不携带 `merchant_id`；
- 不把 Token 写入代码、构建产物、日志或 URL；
- 不用本地假进度冒充真实处理阶段，进度只来自 SSE 的 `step` 事件；
- 不假设按模式必填的字段一定存在，渲染前必须按 `mode` 判断；
- 不为"换一换"发额外请求；
- 不用 `npm run dev` 作为生产服务器；
- 不把 Prototype mock 数据标成真实数据；
- 不为了“先显示”而虚构指标和图表字段；
- 不在未获得用户授权时执行 Git 发布或 Railway 部署。

---

## 12. 前端 Definition of Done

一个前端功能只有满足以下条件才算完成：

- 对应 PRD 用户故事和验收标准已满足；
- 类型完整，无隐式 `any`；
- 后端字段只通过 Adapter 进入组件，Adapter 有契约测试；
- 正常、加载、空、错误和降级状态均已处理；
- 桌面和移动端可用；
- 键盘和基本无障碍可用；
- 组件没有直接依赖不稳定后端实现；
- 相关测试已增加，且不连接真实 LLM；
- `lint`、`format:check`、`test` 和 `build` 通过；
- 如接口变化，OpenAPI 类型和文档已同步；
- 如新增关键路径或目录，`AGENTS.md` 已同步。

---

## 13. 阶段总览

| 阶段 | 内容 | 归属 |
| --- | --- | --- |
| F0 | 工程骨架 + **OpenAPI 类型生成** | P0 |
| F1 | 视觉基础与主布局 | P0 |
| F2 | Mock 会话闭环 | P0 |
| F3 | API 契约与真实会话接入 | P0 |
| F4 | 指标、图表、明细和建议 | P0 |
| F5 | 质量轨迹、反馈与无障碍基础 | P0 |
| **F6** | **Railway 与 MVP 收口** | **P0 · MVP 完成** |
| F7 | 附件与日报 | P1 |
| F8 | 知识库后台 | P1 |
| F9 | 内部可用版收尾 | P1 |

**MVP = F0–F6。** 无障碍基础在 F5 就要满足，不整体延后到 P1。真实认证、`/login`、SSO 属于 P2，不在本表内。

---

## 14. 建议的首批任务

coding agent 可以按以下顺序直接开工：

1. 创建 `frontend/` Vue 3 + TypeScript 工程，`package.json` 的 `name` 设为 `@borough/web`；
2. 配置 Router（`/` 实页 + `/knowledge-base` 占位，无 `/login`）、Pinia、Vitest 和 Playwright；
3. **接入后端提交的 OpenAPI Schema，生成 `api/generated.ts`，搭 `api/adapters/` 与首个契约测试**；
4. 迁移 Prototype Design Tokens，创建 `borough-logo.svg`（不复制旧 Logo）；
5. 创建 `AssistantView.vue` 三栏布局；
6. 创建 `MerchantSwitcher.vue`，两种断点形态（形态已定稿，见 F1）；
7. 创建 Chat Store、Auth Store 和领域类型，消息持有 `clientRequestId`；
8. 实现 `api/sse.ts` 解析器与阶段标签（可先用 mock 事件流驱动）；
9. 用基于生成类型构造的 Mock 完成快速问题闭环；
10. 创建指标口径、图表和建议组件；
11. 创建明细表和质量轨迹；
12. 增加桌面及移动端 Playwright 测试。

第 3 步不能后移。先手写字段再等 OpenAPI，会形成一套本地定义并在接入真实 API 时集中返工。

每完成一个阶段，都应先运行该阶段测试，再进入下一阶段。
