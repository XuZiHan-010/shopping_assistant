# F3 API 契约与真实会话接入设计

## 目标

把 F2 的 Mock 传输层换成真实 HTTP：装配鉴权头与请求 ID、建立统一的 `AppError` 与错误码分支、实现 401 恢复流程、让商家隔离由服务端 Token 决定。

**阶段契约：F3 只换传输层实现和错误语义，不写新 UI。** F2 已经把问答闭环的界面和状态机做完了，本阶段任何「顺手加个面板」的改动都违反约定。图表属于 F4，质量轨迹与反馈属于 F5。

跨阶段决策见 `docs/specs/2026-08-06-frontend-f3-f9-roadmap.md`，本文引用其 A1–A8 编号，不重复论证。

## 范围

覆盖 B0–B7 已就绪的六个业务端点：`POST /api/chat`、`GET|DELETE /api/conversations[/{id}]`、`GET /api/demo/merchants`，外加为 F4/F5 预留的 `GET /api/exports/{id}` 与 `POST /api/answers/{id}/feedback` 的**类型**（Task 0 生成，F3 不调用）。

不做：ECharts 图表、明细表格、CSV 导出入口、质量轨迹面板、反馈按钮、附件。前三项属于 F4，中间两项属于 F5，附件属于 F7。

已完成不重做：`api/chat.ts` 的五个端点封装、`api/sse.ts` 解析器、`api/adapters/chat.ts`、两个 Store 的主路径，全部由 F2 交付。F3 修改它们的错误处理与生命周期，不重建。

## 架构

### 契约再生成先于一切

```text
.worktrees/feature-b5-b6-answer-feedback-export/backend/
  → uv run python ../scripts/export_openapi.py     → docs/api.json、docs/api.md
  → uv run python scripts/export_chat_fixtures.py  → docs/fixtures/chat/*.json
frontend/
  → npm run codegen    → src/api/generated.ts
  → npm run fixtures   → src/api/mock/fixtures.generated.ts
```

主目录的 `docs/api.json` 缺 `/api/answers/{answer_id}/feedback`、`/api/exports/{export_id}` 与 `Feedback*` schema，`ErrorCode` 只有 10 个（缺 `EXPORT_LINK_EXPIRED`、`RATE_LIMITED`、`LLM_BUDGET_EXCEEDED`、`FORBIDDEN`）。不重生成，F4 的导出和 F5 的反馈没有任何类型可写。

`npm run codegen:check` 当前是**通过**的——它只比对 `generated.ts` 与 `docs/api.json` 是否一致，防漂移但防不了源头过期。所以 Task 0 的失败判据是手工的：`grep 'answers/' docs/api.json` 无结果即为 RED。

fixture 必须同批重导。`detail-order.json` 现有的 `export.url` 是 `/api/exports/{id}`，**没有签名查询串**——它早于 B6 的导出服务。按此开发 F4 的导出入口，会写出一个对真实 URL 不成立的实现。

### 分层与 F3 的切入点

```text
Chat Store ──→ api/chat.ts ──→ readChatStream ──→ ChatTransport ──→ 网络
    ↑              ↑              (sse.ts)             ↑
  错误码分支    错误合流                          F3 在这里换实现
  生命周期     防御性降级
```

F2 已把 `ChatTransport` 设计成唯一分叉点，`resolveTransport()` 在 `VITE_USE_MOCK !== 'true'` 时 `throw`。F3 把那个 `throw` 换成 `createFetchTransport()`，其上三层的主路径不动。

### 模块

```text
src/api/
├── errors.ts          AppError、AppErrorCode、工厂函数（新建，见 A1）
├── credentials.ts     凭证提供者注册表（新建，见 A2）
├── client.ts          resolveApiBaseUrl（F0 交付，F3 让它第一次有调用者）
├── transport.ts       加 auth 字段、加 createFetchTransport
└── chat.ts            错误合流：删 ChatStreamError，五个封装补 auth

src/utils/
└── errorCopy.ts       ErrorCode → 中文文案与展示策略（新建）

src/constants/
└── quickQuestions.ts  快速问题脱离 mock（新建，见 A4）
```

`src/utils/errors.ts`（前端方案 §4 目录树写的位置）**不建**，理由见 A1。

### 凭证装配

`src/api/credentials.ts` 是注册表，`main.ts` 在 `app.use(pinia)` 之后注入：

```ts
setCredentialProvider(() => ({ merchantToken: useAuthStore(pinia).selected?.token }))
```

显式传 pinia 实例而不依赖隐式 active pinia，测试里不必构造应用外壳。`src/api/**` 因此永远不 import `src/stores/**`，并由 ESLint `no-restricted-imports` 钉死。

`TransportRequest` 现在就加 `auth?: 'merchant' | 'admin' | 'none'`，不等 F8。`admin` 通道只发 `X-Admin-Token`、**断言不发 `Authorization`**，交叉污染在 F3 就被测试锁死。

## 数据流与状态机

### 错误分类

```text
                        ┌─ 响应头非 2xx ─→ AppError.fromErrorResponse(body, status)
fetch ──→ Response ─────┤
  │                     └─ 2xx ─→ 交给调用方，body 流保持可读
  └─ TypeError ─→ AppError('NETWORK')
                  离线 / DNS 失败 / CORS 预检失败，浏览器不给区分，不猜

流内 event: error ─→ AppError.fromErrorResponse(payload)   ← code 不再丢失
流无 done 也无 error ─→ AppError('STREAM_INTERRUPTED')，可重试
AbortController.abort() ─→ AppError('CANCELLED')
```

**成功路径绝不 `await response.text()`。** 这是 SSE 的命门：错误分支读了 body，流就没了。

`retryable` 取自后端 `ErrorResponse.retryable`，前端表只在后端没给时兜底（A1）。

### 消息状态与错误码的对应

F2 的五态不变，F3 只改「进入 `error` 之后怎么展示、能否重试」：

| 错误码 | 消息状态 | 展示位置 | 动作 |
| --- | --- | --- | --- |
| `NETWORK`、`STREAM_INTERRUPTED`、`INTERNAL_ERROR`、`DATA_SOURCE_UNAVAILABLE` | error | 消息级 | 重试（复用原 `clientRequestId`） |
| `RATE_LIMITED` | error | 消息级 | 提示稍后重试 |
| `LLM_BUDGET_EXCEEDED` | error | 消息级 | 「今日额度已用完」，与普通 5xx 区分 |
| `REQUEST_IN_PROGRESS` | error | 消息级 | 「正在处理中」，**不重复提交** |
| `AUTH_REQUIRED` | error | 全局 | 走 401 恢复流程 |
| `MERCHANT_SCOPE_VIOLATION`、`FORBIDDEN` | error | 全局 | 明确无权限，不显示空数据 |
| `NOT_FOUND` | — | 全局 | 从本地列表移除该项，不停在加载态 |
| `METHOD_NOT_ALLOWED`、`IDEMPOTENCY_KEY_REUSED`、`CONTRACT` | error | 仅上报 | 前端自身缺陷，给用户「请重试」是误导 |
| `CANCELLED` | cancelled | 消息级 | 已取消，可重新回答 |

`METHOD_NOT_ALLOWED` 与 `IDEMPOTENCY_KEY_REUSED` 走 `silent-report`：这两个码出现说明前端调用方式或 ID 复用逻辑有 bug，提示用户重试只会掩盖缺陷。

### 401 恢复

不跳 `/login`（MVP 没有登录页）。顺序：清内存 Token 与 `sessionStorage` 标识 → 打开商家切换器并聚焦 → 提示「演示身份已失效，请重新选择商家」→ **保留用户已输入但未发送的内容**。

### 请求生命周期

F2 的三个会话调用都用一次性 `new AbortController().signal`，既不可取消也不与组件生命周期挂钩。F3 换成命名控制器：切换商家、后发请求覆盖前一次时 abort 掉在途请求，避免旧商家的响应覆盖新商家的列表。

### 历史消息

`ChatMessage` 加 `origin: 'live' | 'history'`（A8）。`retryMessage` 拒绝 `origin === 'history'`——现在对历史消息点重试会发起一次全新的真实计费请求，用户以为是「恢复」。

## 错误处理

`adapters/chat.ts` 现行的 `assertMetricContract` 直接 `throw`，与前端方案 line 681「缺少按模式必填字段时降级展示而非崩溃」冲突。F3 拆成两类：

- **语义不变量违反**继续 `throw CONTRACT`：`analysis_sources` 含未知值、`FALLBACK` 但 `degraded: false`、降级 CHAT 不是 `['FALLBACK']`。这些说明契约真的坏了，渲染下去只会产生误导性界面。
- **按模式字段缺失**改为降级：METRIC 少 `metric_owner` 或少 `visualization` 时返回 `metric: undefined` / `chart: undefined`，并在 `ChatAnswer.contractWarnings: string[]` 留一条，面板显示「该回答未提供指标口径」。

这条边界是 F3 最需要小心的地方。`semanticGuard` 的强断言至今**只被 FakeAgent 的 fixture 验证过**。真实后端（即使用 Fake LLM）只要有一条组合不同，整条回答会被 `ChatContractError` 整个拒掉，表现成「接了真实 API 就全线报错」。F3 验收必须包含对着 b5-b6 后端手工跑通 P0 六种模式各一次。

## 测试策略

传输层用 stub `fetch` 测装配：GET 不带 `Content-Type`、POST 带且 body 已序列化、`accept` 透传、每次请求有唯一 `X-Request-Id`、`credentials: 'omit'` 与 `cache: 'no-store'` 显式存在。**专门一条断言 200 响应返回后 `response.body` 仍可读**——这是最容易在写错误分支时破坏的不变量。

错误文案表用穷尽性测试：遍历 `generated.ts` 的 `ErrorCode` 联合，每个都能取到非空 `title`。`Record` 类型本身在 typecheck 阶段就会挡住遗漏，运行时测试防的是有人把它改成 `Partial`。

凭证测试断言 `admin` 通道**不发** `Authorization`、`merchant` 通道不发 `X-Admin-Token`、token 不出现在任何抛出的 `message` 里。

Store 测试改成表驱动：对每个错误码断言 `(消息状态, 是否可重试, 是否保留用户输入, 展示位置)` 四元组。重点两条——`REQUEST_IN_PROGRESS` 不得标成普通 error 后立即又允许重试（会打成循环），`IDEMPOTENCY_KEY_REUSED` 不给用户「请重试」。

401 恢复只做组件测试，不做 e2e：在 Mock 里开一个「过期 token」后门成本高于收益，而且那个后门本身会成为下一个 mock 泄漏源。

隔离 e2e 必须做：Mock 传输层按 token 分租户后（A3），切商家看不到上一个商家的会话——这条在 Mock 下才有意义，因为 Playwright 强制 `VITE_USE_MOCK=true`。

## 边界

不引入新运行时依赖。不写 UI 组件，不改 `insights/` 下任何面板。不建登录页。不调用真实 LLM——手工验收对着 Fake LLM 的后端跑。

组件仍不直接引用 `generated.ts`，转换点仍只有 `api/adapters/chat.ts`。

不把 DOM、ECharts 实例或 `File` 对象存入 Store。

Token 只进内存与请求头，不写 `localStorage`、URL、日志或构建产物。前端任何请求都不携带 `merchant_id`。
