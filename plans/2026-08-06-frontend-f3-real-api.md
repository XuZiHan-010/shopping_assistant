# Frontend F3 API 契约与真实会话接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended)
> or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 F2 的 Mock 传输层换成真实 HTTP，建立统一 `AppError` 与错误码分支、凭证装配、401 恢复流程，并让商家隔离由服务端 Token 决定。

**Architecture:** `api/errors.ts` 定义协议层错误，`utils/errorCopy.ts` 定义展示策略，两者用 `Record<AppErrorCode, ErrorCopy>` 强制穷尽。`api/credentials.ts` 做凭证注册表，由 `main.ts` 注入，使 `src/api/**` 永不 import `src/stores/**`。`api/transport.ts` 的 `resolveTransport()` 从抛异常改为返回 `createFetchTransport()`，其上的 `sse.ts`、`api/chat.ts`、两个 Store 的主路径不变。

**Tech Stack:** Vue 3、TypeScript、Pinia、Vitest、Vue Test Utils、Playwright、ESLint、openapi-typescript。

## Global Constraints

- 所有用户可见文案使用中文，代码标识符使用英文。
- 跨阶段决策以 `docs/specs/2026-08-06-frontend-f3-f9-roadmap.md` 的 A1–A8 为准，本计划不重新裁决。
- F3 不写 UI 组件、不改 `src/components/insights/**`。图表属于 F4，质量轨迹与反馈属于 F5，附件属于 F7。
- 组件不直接消费 `src/api/generated.ts`，也不自行转换字段；转换点只有 `src/api/adapters/chat.ts`。
- Token 只进内存与请求头，不写 `localStorage`、URL、日志或构建产物；任何请求都不携带 `merchant_id`。
- 不使用原生 `EventSource`；不创建 `/login` 路由或 `LoginView.vue`。
- 不使用 `any` 掩盖接口问题；不用本地假进度冒充真实处理阶段。
- `yshopping-prototype/` 与 `yshopping-merchant-ai 4/` 只读。
- 除 Task 0 外不得手改 `docs/api.json` 与 `src/api/generated.ts`。
- 单元测试不连接真实 LLM；手工验收对着 Fake LLM 的后端进行。
- 项目规则禁止未经明确授权的 Git commit/push/tag/PR；本计划的每项以测试通过替代 commit。

**建议的执行断点：** Task 0–3 交付契约与传输层。在 Task 3 结束处做一次完整门禁，并用 `VITE_USE_MOCK=false` 手动对着 b5-b6 后端跑通一次问答，再动 Store 与视图。传输层与状态机混在一次调试里，分不清是请求装配错还是状态机错。

---

### Task 0: 重新生成 OpenAPI 契约与 Chat Fixture

**Files:**
- Modify: `docs/api.json`
- Modify: `docs/api.md`
- Modify: `docs/fixtures/chat/*.json`
- Modify: `frontend/src/api/generated.ts`
- Modify: `frontend/src/api/mock/fixtures.generated.ts`

**Interfaces:**
- Produces: `components['schemas']['FeedbackRequest' | 'FeedbackResponse' | 'FeedbackReaction']`、
  `paths['/api/answers/{answer_id}/feedback']`、`paths['/api/exports/{export_id}']`、
  含 14 个成员的 `components['schemas']['ErrorCode']`。
- Consumes: `.worktrees/feature-b5-b6-answer-feedback-export/backend/`。

- [ ] **Step 1: 确认契约确实过期。**

  本任务的失败判据是手工的——`npm run codegen:check` 当前**通过**，因为它只比对
  `generated.ts` 与 `docs/api.json` 是否一致，防漂移但防不了源头过期。

  Run: `grep -c 'answers/' docs/api.json; grep -c 'EXPORT_LINK_EXPIRED' docs/api.json`（工作目录为仓库根）

  Expected: 两条均输出 `0`，即两条路径与四个错误码都不存在。这就是 RED。

- [ ] **Step 2: 确认最新后端的位置。**

  Run: `git worktree list`

  Expected: 输出含 `.worktrees/feature-b5-b6-answer-feedback-export`（分支
  `feature/b5-b6-answer-feedback-export`）。若主目录已合并该分支，则直接用主目录的 `backend/`，
  并在报告里记录这一事实。

- [ ] **Step 3: 重新导出 OpenAPI 与 fixture。**

  在最新后端所在工作树的 `backend/` 下依次执行：

  ```powershell
  uv run python ../scripts/export_openapi.py
  uv run python scripts/export_chat_fixtures.py
  ```

  两个产物都要，不能只导 OpenAPI。`docs/fixtures/chat/detail-order.json` 现有的
  `export.url` 是 `/api/exports/{id}`，**没有 `?merchant_id=&expires_at=&signature=`**——
  它早于 B6 的导出服务。不重导，F4 的导出入口会对着一个不存在的 URL 形状开发。

  若导出发生在 worktree 内，把 `docs/api.json`、`docs/api.md`、`docs/fixtures/chat/*.json`
  同步回前端所在的工作树。

- [ ] **Step 4: 重新生成前端类型与 fixture 镜像。**

  Run: `npm run codegen; npm run fixtures`（工作目录 `frontend/`）

- [ ] **Step 5: 验证契约完整。**

  Run: `npm run codegen:check; npm run fixtures:check; npm run typecheck; npm run test`（工作目录 `frontend/`）

  Expected: 四条全部退出码为 0。

  再手工核对三项：`grep -c 'answers/' docs/api.json` 非 0；`src/api/generated.ts` 的
  `ErrorCode` 联合含 14 个成员；`docs/fixtures/chat/detail-order.json` 的 `export.url`
  含 `signature=`。

  若 `typecheck` 在这一步报错，**不要改 `fixtures.generated.ts` 绕过**——镜像用
  `as const satisfies ChatResponse` 声明，报错说明 b5-b6 的 `ChatResponse` 有不兼容变化，
  应当回去查后端导出。这正是该声明方式的设计意图。

---

### Task 1: 建立 AppError 与错误文案表

**Files:**
- Create: `frontend/src/api/errors.ts`
- Create: `frontend/src/api/errors.spec.ts`
- Create: `frontend/src/utils/errorCopy.ts`
- Create: `frontend/src/utils/errorCopy.spec.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/sse.ts`
- Modify: `frontend/src/api/adapters/chat.ts`

**Interfaces:**
- Produces: `AppError`、`AppErrorCode`、`toAppError(unknown): AppError`、
  `AppError.fromErrorResponse(payload, status?)`、`AppError.fromNetwork(cause)`、
  `describeError(error: AppError): ErrorCopy`。
- Consumes: `components['schemas']['ErrorResponse' | 'ErrorCode']`。

- [ ] **Step 1: 写失败的 AppError 测试。**

  ```ts
  it('AbortError 归一为 CANCELLED', () => {
    expect(toAppError(new DOMException('', 'AbortError')).code).toBe('CANCELLED')
  })

  it('retryable 以后端返回为准，不由前端表推断', () => {
    const error = AppError.fromErrorResponse(
      { code: 'RATE_LIMITED', message: '请求过多', request_id: 'r-1', details: [], retryable: true },
      429,
    )
    expect(error.retryable).toBe(true)
    expect(error.requestId).toBe('r-1')
    expect(error.status).toBe(429)
  })

  it('未知错误码不被静默吞掉', () => {
    const error = AppError.fromErrorResponse(
      { code: 'SOMETHING_NEW', message: 'x', request_id: 'r-2', details: [], retryable: false } as never,
      418,
    )
    expect(error.code).toBe('HTTP_ERROR')
    expect(error.shouldReport).toBe(true)
  })
  ```

- [ ] **Step 2: 写失败的文案穷尽性测试。**

  ```ts
  const BACKEND_CODES = [
    'AUTH_REQUIRED', 'MERCHANT_SCOPE_VIOLATION', 'NOT_FOUND', 'METHOD_NOT_ALLOWED',
    'INVALID_REQUEST', 'IDEMPOTENCY_KEY_REUSED', 'REQUEST_IN_PROGRESS',
    'DATA_SOURCE_UNAVAILABLE', 'EXPORT_LINK_EXPIRED', 'RATE_LIMITED',
    'LLM_BUDGET_EXCEEDED', 'FORBIDDEN', 'HTTP_ERROR', 'INTERNAL_ERROR',
  ] as const satisfies readonly components['schemas']['ErrorCode'][]

  it.each([...BACKEND_CODES, 'CONFIG', 'NETWORK', 'CANCELLED', 'STREAM_INTERRUPTED', 'CONTRACT'])(
    '%s 有非空中文文案', (code) => {
      const copy = describeError(new AppError(code as AppErrorCode, 'x'))
      expect(copy.title.length).toBeGreaterThan(0)
      expect(copy.detail.length).toBeGreaterThan(0)
    },
  )

  it('LLM_BUDGET_EXCEEDED 与普通 5xx 文案不同', () => {
    expect(describeError(new AppError('LLM_BUDGET_EXCEEDED', 'x')).title)
      .not.toBe(describeError(new AppError('INTERNAL_ERROR', 'x')).title)
  })

  it('前端自身缺陷类错误只上报，不提示用户重试', () => {
    for (const code of ['METHOD_NOT_ALLOWED', 'IDEMPOTENCY_KEY_REUSED', 'CONTRACT'] as const) {
      expect(describeError(new AppError(code, 'x')).surface).toBe('silent-report')
    }
  })
  ```

  `BACKEND_CODES` 的 `satisfies` 声明是关键：后端新增错误码时，这个数组会因缺项而
  在 typecheck 阶段失败，测试无需手工维护也不会漏。

- [ ] **Step 3: 运行测试确认失败。**

  Run: `npm run test -- src/api/errors.spec.ts src/utils/errorCopy.spec.ts`（工作目录 `frontend/`）

  Expected: FAIL，因为两个模块尚不存在。

- [ ] **Step 4: 实现 AppError。**

  ```ts
  export type LocalErrorCode =
    | 'CONFIG' | 'NETWORK' | 'CANCELLED' | 'STREAM_INTERRUPTED' | 'CONTRACT'
  export type AppErrorCode = components['schemas']['ErrorCode'] | LocalErrorCode

  export class AppError extends Error {
    readonly code: AppErrorCode
    readonly status?: number
    readonly requestId?: string
    readonly retryable: boolean
    readonly details?: unknown
    readonly shouldReport: boolean
    // ...
  }
  ```

  `fromErrorResponse` 用 `generated.ts` 的枚举成员集合校验 `code`；不在集合内时降级为
  `HTTP_ERROR` 并置 `shouldReport = true`——这是「遇到表中没有的码时按通用错误展示并上报」
  （前端方案 §10）的落点。`retryable` 直接取载荷的值。

  `toAppError` 是兜底漏斗：已是 `AppError` 原样返回；`name === 'AbortError'` 的
  `DOMException` 转 `CANCELLED`；`TypeError` 转 `NETWORK`；其余转 `INTERNAL_ERROR`
  并置 `shouldReport`。

- [ ] **Step 5: 实现文案表。**

  ```ts
  interface ErrorCopy {
    title: string
    detail: string
    surface: 'message' | 'global' | 'silent-report'
    action: 'retry' | 'reselect-merchant' | 'reask' | 'none'
  }
  const COPY: Record<AppErrorCode, ErrorCopy> = { /* 19 项，一项不少 */ }
  ```

  用 `Record` 而非 `Partial` + default 分支：后端加错误码时 typecheck 直接失败，
  而不是静默落进 default。这是本任务真正的防线，运行时测试只是防有人改成 `Partial`。

  `AUTH_REQUIRED` 的 `action` 是 `reselect-merchant`，`EXPORT_LINK_EXPIRED` 是 `reask`，
  `METHOD_NOT_ALLOWED` / `IDEMPOTENCY_KEY_REUSED` / `CONTRACT` 的 `surface` 是 `silent-report`。

- [ ] **Step 6: 把现有四个错误类改成 AppError 子类。**

  `ApiConfigError extends AppError`（`CONFIG`）、`ChatStreamInterruptedError extends AppError`
  （`STREAM_INTERRUPTED`，`retryable: true`）、`ChatContractError extends AppError`
  （`CONTRACT`，`shouldReport: true`）。类名与 `instanceof` 行为保持不变，现有测试不受影响。

  `ChatStreamError` 在 Task 4 删除，本步不动。

- [ ] **Step 7: 运行测试。**

  Run: `npm run test -- src/api src/utils`（工作目录 `frontend/`）

  Expected: PASS，且 `src/api/client.spec.ts`、`src/api/sse.spec.ts`、
  `src/api/adapters/chat.spec.ts` 的既有用例全部保持通过——本任务不改变任何对外行为。

---

### Task 2: 凭证提供者与请求装配

**Files:**
- Create: `frontend/src/api/credentials.ts`
- Create: `frontend/src/api/credentials.spec.ts`
- Modify: `frontend/src/api/transport.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/eslint.config.js`

**Interfaces:**
- Produces: `setCredentialProvider(fn | undefined)`、`buildAuthHeaders(scope): Record<string, string>`、
  `TransportRequest.auth?: 'merchant' | 'admin' | 'none'`。
- Consumes: `AppError`（Task 1）。

- [ ] **Step 1: 写失败的凭证装配测试。**

  ```ts
  it('merchant 通道只发 Authorization', () => {
    setCredentialProvider(() => ({ merchantToken: 'demo-token-100', adminToken: 'admin-secret' }))
    const headers = buildAuthHeaders('merchant')
    expect(headers.Authorization).toBe('Bearer demo-token-100')
    expect(headers['X-Admin-Token']).toBeUndefined()
  })

  it('admin 通道只发 X-Admin-Token，绝不发 Authorization', () => {
    setCredentialProvider(() => ({ merchantToken: 'demo-token-100', adminToken: 'admin-secret' }))
    const headers = buildAuthHeaders('admin')
    expect(headers['X-Admin-Token']).toBe('admin-secret')
    expect(headers.Authorization).toBeUndefined()
  })

  it('none 通道不发任何凭证', () => {
    expect(buildAuthHeaders('none')).toEqual({})
  })

  it('缺凭证时快速失败，不发出注定 401 的请求', () => {
    setCredentialProvider(() => ({}))
    expect(() => buildAuthHeaders('merchant')).toThrow(
      expect.objectContaining({ code: 'AUTH_REQUIRED' }),
    )
  })

  it('抛出的错误不泄漏 token 明文', () => {
    setCredentialProvider(() => ({ merchantToken: undefined, adminToken: 'admin-secret' }))
    try { buildAuthHeaders('merchant') } catch (error) {
      expect((error as Error).message).not.toContain('admin-secret')
    }
  })
  ```

  第二条是为 F8 提前设的防线：管理员令牌绝不出现在商家接口上，反之亦然。

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/api/credentials.spec.ts`

  Expected: FAIL，因为模块尚不存在。

- [ ] **Step 3: 实现凭证注册表并接入 transport。**

  `credentials.ts` **不 import 任何 store**，只持有一个模块级 provider 函数。
  `TransportRequest` 加 `auth?: 'merchant' | 'admin' | 'none'`，默认 `'merchant'`。

- [ ] **Step 4: 在 main.ts 注入 provider。**

  ```ts
  const pinia = createPinia()
  app.use(pinia)
  setCredentialProvider(() => ({ merchantToken: useAuthStore(pinia).selected?.token }))
  ```

  显式传 pinia 实例，不依赖隐式 active pinia——否则单测必须构造应用外壳才能调 provider。

- [ ] **Step 5: 用 ESLint 钉死依赖方向。**

  在 `eslint.config.js` 增加一段针对 `files: ['src/api/**']` 的 `no-restricted-imports`，
  禁止 `@/stores/*` 与相对路径形式的 store 引用。循环一旦被规则挡住就再也回不来了，
  比写在文档里靠评审可靠。

- [ ] **Step 6: 运行测试与 lint。**

  Run: `npm run test -- src/api/credentials.spec.ts; npm run lint`

  Expected: 两条均退出码为 0。

  再做一次反向验证：临时在 `src/api/transport.ts` 顶部加一行
  `import { useAuthStore } from '@/stores/auth'`，`npm run lint` 必须**失败**；
  确认后删除该行。规则不验证就等于没有。

---

### Task 3: 实现真实传输层

**Files:**
- Modify: `frontend/src/api/transport.ts`
- Create: `frontend/src/api/transport.spec.ts`

**Interfaces:**
- Produces: `createFetchTransport(): ChatTransport`；`resolveTransport()` 在
  `VITE_USE_MOCK !== 'true'` 时返回真实实现而不再抛异常。
- Consumes: `resolveApiBaseUrl()`（`api/client.ts`，F0 交付，本任务让它第一次有调用者）、
  `buildAuthHeaders()`（Task 2）、`AppError`（Task 1）。

- [ ] **Step 1: 写失败的传输层测试。**

  ```ts
  it('GET 不带 Content-Type，POST 带且 body 已序列化', async () => { /* stub fetch，断言入参 */ })

  it('每次请求带唯一 X-Request-Id', async () => { /* 两次调用，断言两个 id 不同且非空 */ })

  it('2xx 响应返回后 body 流仍可读', async () => {
    const transport = createFetchTransport()
    const response = await transport({ path: '/api/chat', method: 'POST', body: {} }, signal)
    expect(response.body).not.toBeNull()
    const chunk = await response.body!.getReader().read()
    expect(chunk.done).toBe(false)
  })

  it('401 的 JSON body 转成带 requestId 的 AppError', async () => { /* code === 'AUTH_REQUIRED' */ })

  it('非 JSON body 的 502 转成 HTTP_ERROR 并保留 status', async () => { /* status === 502 */ })

  it('fetch 抛 TypeError 转成 NETWORK', async () => { /* code === 'NETWORK' */ })
  ```

  第三条是本任务最重要的断言，也是最容易被破坏的不变量：错误分支若在成功路径上
  `await response.text()`，SSE 的流就没了，而单元测试很容易恰好测不到。

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/api/transport.spec.ts`

  Expected: FAIL，因为 `createFetchTransport` 尚不存在。

- [ ] **Step 3: 实现 createFetchTransport。**

  ```ts
  export function createFetchTransport(): ChatTransport {
    return async (req, signal) => {
      const base = resolveApiBaseUrl()
      const headers: Record<string, string> = {
        ...buildAuthHeaders(req.auth ?? 'merchant'),
        'X-Request-Id': crypto.randomUUID(),
      }
      if (req.accept) headers.Accept = req.accept
      if (req.body !== undefined) headers['Content-Type'] = 'application/json'

      let response: Response
      try {
        response = await fetch(`${base}${req.path}`, {
          method: req.method,
          headers,
          body: req.body === undefined ? undefined : JSON.stringify(req.body),
          signal,
          credentials: 'omit',
          cache: 'no-store',
        })
      } catch (cause) {
        throw toAppError(cause)   // AbortError → CANCELLED；TypeError → NETWORK
      }

      if (!response.ok) throw await toHttpError(response)
      return response            // ← 成功路径绝不读 body
    }
  }
  ```

  `toHttpError` 只在 `!response.ok` 分支里 `await response.json()`，解析失败时退回
  `HTTP_ERROR` 并保留 `status`。`NETWORK` 的文案要诚实——离线、DNS 失败、CORS 预检失败
  浏览器都不给区分，写成「无法连接后端服务，请检查网络或后端地址配置」，不猜具体原因。

  `resolveTransport()` 的 `throw` 换成 `createFetchTransport()`。

- [ ] **Step 4: 运行测试。**

  Run: `npm run test -- src/api/transport.spec.ts src/api/mock/transport.spec.ts`

  Expected: PASS，且 Mock 路径的既有用例全部保持通过。

- [ ] **Step 5: 完整门禁与真实后端手工验证（执行断点）。**

  Run: `npm run lint; npm run format:check; npm run codegen:check; npm run fixtures:check; npm run typecheck; npm run test; npm run build`（工作目录 `frontend/`）

  Expected: 全部退出码为 0。

  然后起 b5-b6 后端（Fake LLM，不配 `LLM_API_KEY`），前端用
  `VITE_USE_MOCK=false VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev` 启动，
  手工发一条 GMV 问题，确认能拿到回答。此时 Store 尚未改造，错误展示仍是 F2 的形态，
  只验证请求装配与 SSE 通路。结果写入任务报告。

---

### Task 4: 错误合流与 Adapter 防御性降级

**Files:**
- Modify: `frontend/src/api/chat.ts`
- Modify: `frontend/src/api/chat.spec.ts`
- Modify: `frontend/src/api/adapters/chat.ts`
- Modify: `frontend/src/api/adapters/chat.spec.ts`
- Modify: `frontend/src/types/chat.ts`

**Interfaces:**
- Produces: `ChatAnswer.contractWarnings: string[]`；五个端点封装带上 `auth` 归属；
  `listConversations(limit?)`。
- Consumes: `AppError`（Task 1）。
- Delete: `ChatStreamError`。

- [ ] **Step 1: 写失败的流内错误码测试。**

  ```ts
  it('流内 error 事件保留后端错误码，不退化成通用消息', async () => {
    // transport 返回一个 event: error，载荷 code = 'LLM_BUDGET_EXCEEDED'
    await expect(submitChat(input, handlers, signal)).rejects.toMatchObject({
      code: 'LLM_BUDGET_EXCEEDED',
      requestId: expect.any(String),
    })
  })

  it('流无 done 也无 error 时标记为可重试', async () => {
    await expect(submitChat(input, handlers, signal)).rejects.toMatchObject({
      code: 'STREAM_INTERRUPTED', retryable: true,
    })
  })

  it('demo/merchants 不带 Authorization', async () => { /* 断言 transport 收到 auth === 'none' */ })
  ```

  第一条是删除 `ChatStreamError` 的理由：它只保留 `event.error.message`，把 `code` 和
  `request_id` 丢了，`LLM_BUDGET_EXCEEDED` 因此无法与普通 5xx 区分。

- [ ] **Step 2: 写失败的 Adapter 降级测试。**

  ```ts
  it('METRIC 缺按模式字段时降级而非抛异常', () => {
    const raw = { ...CHAT_FIXTURES.metricGmv, metric_owner: null }
    const answer = toChatAnswer(raw as never)
    expect(answer.metric).toBeUndefined()
    expect(answer.contractWarnings).toHaveLength(1)
    expect(answer.answer.length).toBeGreaterThan(0)   // 正文照常可读
  })

  it('语义不变量违反时仍然抛 CONTRACT', () => {
    const raw = { ...CHAT_FIXTURES.metricGmv, degraded: true, degraded_reason: null }
    expect(() => toChatAnswer(raw as never)).toThrow(
      expect.objectContaining({ code: 'CONTRACT' }),
    )
  })
  ```

  两类必须分开：按模式字段缺失只影响一个面板，降级展示是对的；语义不变量违反说明契约
  真的坏了，继续渲染只会产生误导性界面。

- [ ] **Step 3: 运行测试确认失败。**

  Run: `npm run test -- src/api/chat.spec.ts src/api/adapters/chat.spec.ts`

  Expected: FAIL，因为 `contractWarnings` 不存在且 `assertMetricContract` 仍然直接抛异常。

- [ ] **Step 4: 实现错误合流与降级。**

  `api/chat.ts` 删掉 `ChatStreamError`，流内 `event: error` 直接
  `throw AppError.fromErrorResponse(event.error)`。五个封装补 `auth`：
  `listDemoMerchants` 用 `'none'`，其余用默认 `'merchant'`。`listConversations` 接
  `limit` 参数（默认 50，见路线图 A8-6）。

  `adapters/chat.ts` 把 `assertMetricContract` 从「抛异常」改为「收集 warning」：

  ```ts
  function collectMetricWarnings(raw: RawChatResponse): string[] {
    if (raw.answer_mode !== 'METRIC') return []
    const missing = METRIC_FIELDS.filter((f) => raw[f] === null || raw[f] === undefined)
    const warnings = missing.length ? [`METRIC 回答缺少 ${missing.join('、')}，指标口径面板将显示空状态`] : []
    if (!raw.visualization) warnings.push('METRIC 回答缺少 visualization，图表面板将显示空状态')
    return warnings
  }
  ```

  `toMetric` 在任一必填字段缺失时返回 `undefined`，不伪造默认值。`semanticGuard` 不动——
  它管的正是语义不变量那一类。

- [ ] **Step 5: 运行测试。**

  Run: `npm run test -- src/api`

  Expected: PASS，且 Adapter 契约测试仍覆盖 P0 六种模式的全部 fixture 载荷。

---

### Task 5: Chat Store 的错误码分支与请求生命周期

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/stores/chat.spec.ts`
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/components/chat/ChatMessage.vue`
- Modify: `frontend/src/components/chat/ChatMessage.spec.ts`

**Interfaces:**
- Produces: `ChatMessage.error?: AppError`（取代 `errorMessage?: string`）、
  `ChatMessage.origin: 'live' | 'history'`。
- Consumes: `describeError()`（Task 1）。

- [ ] **Step 1: 写失败的错误码表驱动测试。**

  ```ts
  const CASES = [
    { code: 'RATE_LIMITED',          status: 'error',     retryable: true  },
    { code: 'LLM_BUDGET_EXCEEDED',   status: 'error',     retryable: true  },
    { code: 'REQUEST_IN_PROGRESS',   status: 'error',     retryable: false },
    { code: 'IDEMPOTENCY_KEY_REUSED',status: 'error',     retryable: false },
    { code: 'CANCELLED',             status: 'cancelled', retryable: true  },
  ] as const

  it.each(CASES)('$code → $status', async ({ code, status, retryable }) => { /* … */ })

  it('取消仍然是 cancelled 而不是 error', async () => {
    // 回归防线：Task 1 把错误统一包成 AppError 后，
    // 原先 (error as Error).name === 'AbortError' 的判断会静默失效
  })

  it('历史消息不可重试', async () => {
    await store.loadConversation('c-1')
    const assistant = store.messages.find((m) => m.role === 'assistant')!
    expect(await store.retryMessage(assistant.localId)).toBe(false)
  })
  ```

  `REQUEST_IN_PROGRESS` 标为不可重试是有意的：后端说这条请求正在处理，再点重试会打成循环。
  UI 展示「正在处理中」，等待而非重发。

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/stores/chat.spec.ts`

  Expected: FAIL，因为 Store 仍用 `errorMessage` 字符串且无 `origin` 字段。

- [ ] **Step 3: 改造 Store。**

  `runRound` 的 `catch` 从字符串比对改为错误码分支：

  ```ts
  } catch (raw) {
    const error = toAppError(raw)
    assistant.status = error.code === 'CANCELLED' ? 'cancelled' : 'error'
    assistant.error = error
  }
  ```

  **`stores/chat.ts` 原先靠 `(error as Error).name === 'AbortError'` 判取消，这一行必须
  与本任务同批改。** Task 1 把错误统一包成 `AppError` 之后，`name` 变成 `'AppError'`，
  该判断会静默失效，表现为用户每次点「停止」都看到「出错了」。

  Store 只存 `AppError`，不存文案；文案由 `ChatMessage.vue` 调 `describeError()` 得到——
  同一个错误在消息级和全局提示条里措辞不同，把文案存进 Store 就只能有一套。

  三个会话调用的一次性 `new AbortController()` 换成命名控制器，切换商家与后发请求覆盖
  前一次时 abort 在途请求，避免旧商家的响应覆盖新商家的列表。

  `loadConversation` 给每条消息置 `origin: 'history'`，`submitMessage` 置 `'live'`；
  `retryMessage` 在 `origin === 'history'` 时直接返回 `false`。

- [ ] **Step 4: 验证 session_id 语义。**

  `loadConversation` 现在假设「会话 id 就是 `/api/chat` 的 `session_id`」。读
  `backend/app/api/routes/chat.py` 与 `backend/app/schemas/chat.py` 确认这一点。

  成立则在代码注释里写明依据；不成立则加载历史后追问会静默开一个新会话，必须修正并在
  任务报告里记录。

- [ ] **Step 5: 运行测试。**

  Run: `npm run test -- src/stores src/components/chat`

  Expected: PASS。

---

### Task 6: 401 恢复流程

**Files:**
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/stores/auth.spec.ts`
- Modify: `frontend/src/views/AssistantView.vue`
- Modify: `frontend/src/views/AssistantView.spec.ts`
- Modify: `frontend/src/components/chat/ChatComposer.vue`

**Interfaces:**
- Produces: `useAuthStore().invalidate()`；`AssistantView` 在收到 `AUTH_REQUIRED` 时打开切换器。
- Consumes: `AppError`、`describeError()`。

- [ ] **Step 1: 写失败的 401 恢复测试。**

  ```ts
  it('401 清凭证、开切换器、保留未发送输入，且不跳路由', async () => {
    // transport 对 POST /api/chat 抛 AppError('AUTH_REQUIRED')
    const wrapper = mount(AssistantView, { /* … */ })
    await wrapper.get('textarea').setValue('昨天的 GMV 是多少')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(useAuthStore().selected?.token).toBeUndefined()
    expect(sessionStorage.getItem(MERCHANT_STORAGE_KEY)).toBeNull()
    expect(wrapper.get('[data-testid="merchant-switcher"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('textarea').element.value).toBe('昨天的 GMV 是多少')
    expect(router.currentRoute.value.path).toBe('/')
  })
  ```

  最后两条断言是这个任务存在的理由：MVP 没有登录页，跳 `/login` 会进 404；
  清掉用户刚写完的问题则是把一次身份失效变成一次数据丢失。

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/views/AssistantView.spec.ts`

  Expected: FAIL，因为 `invalidate()` 不存在且没有 401 处理路径。

- [ ] **Step 3: 实现恢复流程。**

  `authStore.invalidate()` 清内存 Token 与 `sessionStorage` 标识，置
  `restoreNotice = '演示身份已失效，请重新选择商家。'`，但**保留 `merchants` 列表**——
  列表是公开数据，重新拉一次没有必要。

  `AssistantView` 监听 Store 抛出的 `AUTH_REQUIRED`，调 `invalidate()` 后打开切换器并聚焦。
  `ChatComposer` 的文本在提交失败时不清空（现在是提交即清），改为只在
  `submitMessage` 返回 `true` 时清空。

- [ ] **Step 4: 运行测试。**

  Run: `npm run test -- src/views src/stores/auth.spec.ts src/components/chat/ChatComposer.spec.ts`

  Expected: PASS。

---

### Task 7: 商家隔离改由 Token 决定

**Files:**
- Modify: `frontend/src/api/mock/transport.ts`
- Modify: `frontend/src/api/mock/transport.spec.ts`
- Modify: `frontend/src/api/transport.ts`
- Modify: `frontend/src/views/AssistantView.vue`
- Create: `frontend/e2e/isolation.spec.ts`

**Interfaces:**
- Produces: Mock 传输层按 `Authorization` 头分租户。
- Delete: 应用代码中的 `resetTransportCache()` 调用。

- [ ] **Step 1: 写失败的 Mock 隔离测试。**

  ```ts
  it('同一传输实例下，商家之间的会话互不可见', async () => {
    const transport = createMockTransport()
    await submitVia(transport, 'demo-token-100', '昨天的 GMV 是多少')
    const listForB = await listVia(transport, 'demo-token-101')
    expect(listForB.items).toHaveLength(0)
  })
  ```

  真实后端按 Token 过滤，本就不需要 `resetTransportCache()`；但 Playwright 强制
  `VITE_USE_MOCK=true`，Mock 不实现同样语义，隔离 e2e 就是假绿。

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/api/mock/transport.spec.ts`

  Expected: FAIL，因为 Mock 的会话表是全局单表。

- [ ] **Step 3: 实现按 Token 分租户并移除应用侧缓存重置。**

  Mock 的 `Map<id, Conversation>` 改成 `Map<token, Map<id, Conversation>>`，key 取自
  收到的 `Authorization` 头。`AssistantView.selectMerchant()` 去掉 `resetTransportCache()`，
  保留 `chatStore.reset()` + `clearConversations()` + `refreshConversations()`。

  `resetTransportCache` 本身保留在 `transport.ts` 供测试使用，但不再被应用代码调用。

- [ ] **Step 4: 写隔离 E2E。**

  ```ts
  test('切换商家后看不到上一个商家的会话', async ({ page }) => {
    // 商家 A 完成一轮问答 → 打开抽屉确认有会话
    // 切到商家 B → 打开抽屉 → 断言列表为空
  })
  ```

- [ ] **Step 5: 运行测试并验证调用点已清除。**

  Run: `npm run test -- src/api/mock; npm run test:e2e -- e2e/isolation.spec.ts`

  Expected: 两条均退出码为 0。

  Run: `grep -rn "resetTransportCache" frontend/src/views frontend/src/components`

  Expected: 无输出。

---

### Task 8: 快速问题脱离 Mock 与生产构建门禁

**Files:**
- Create: `frontend/src/constants/quickQuestions.ts`
- Create: `frontend/src/constants/quickQuestions.spec.ts`
- Modify: `frontend/src/components/chat/ConversationColumn.vue`
- Modify: `frontend/src/components/chat/ConversationColumn.spec.ts`
- Modify: `frontend/src/api/mock/scenarios.ts`
- Modify: `frontend/scripts/check-no-mock-payload.mjs`
- Modify: `frontend/eslint.config.js`
- Modify: `frontend/.env.example`

**Interfaces:**
- Produces: `QUICK_QUESTIONS: readonly { category: string; question: string }[]`。
- Consumes: 无（纯常量，`api/mock/scenarios.ts` 反过来消费它）。

- [ ] **Step 1: 写失败的常量与依赖方向测试。**

  ```ts
  it('欢迎卡片的快速问题来自常量而非 mock', () => {
    const wrapper = mount(ConversationColumn, { /* … */ })
    const rendered = wrapper.findAll('[data-testid="quick-question"]').map((n) => n.text())
    expect(rendered).toEqual(QUICK_QUESTIONS.map((q) => q.question))
  })

  it('mock 场景与快速问题常量不漂移', () => {
    for (const { question } of QUICK_QUESTIONS) {
      expect(matchScenario(question)).not.toBe('chatGreeting')   // 每条都有专属 fixture
    }
  })
  ```

  第二条防的是「改了常量但忘了改 mock 映射」，那会让快速问题静默退化成问候语兜底，
  而「每个快速问题均可完成一轮问答」这条验收表面上仍然通过。

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/constants src/components/chat/ConversationColumn.spec.ts`

  Expected: FAIL，因为常量模块尚不存在。

- [ ] **Step 3: 建立常量并反转依赖方向。**

  快速问题是产品文案，不是接口数据——后端没有 quick-questions 端点，
  `ChatResponse.suggestions` 只在回答之后才有。`api/mock/scenarios.ts` 改为从
  `QUICK_QUESTIONS` 派生它的四个有 `category` 的场景，这样两边永不漂移。

  `ConversationColumn.vue` 改 import 源。

- [ ] **Step 4: 加 ESLint 规则并更新门禁脚本注释。**

  `no-restricted-imports`：`src/**`（排除 `src/api/mock/**` 与 `**/*.spec.ts`）不得
  import `@/api/mock/*`。

  `scripts/check-no-mock-payload.mjs` 顶部注释现在写着「scenarios.ts 从 Task 7 起就是被
  ConversationColumn 静态引用的应用代码」——这条前提在本任务之后不成立，改掉它，
  否则下一个人会据此认为 mock 泄漏是设计意图。

  `.env.example` 的 `VITE_USE_MOCK` 注释从「F3 时改为 false」改为说明当前两种取值的用途。

- [ ] **Step 5: 运行测试与生产构建门禁。**

  Run: `npm run test -- src/constants src/components; npm run lint; npm run build; npm run mock:check`（工作目录 `frontend/`，构建时不设 `VITE_USE_MOCK`）

  Expected: 全部退出码为 0，构建产物中不含任何 fixture 文本。

  同样做一次反向验证：临时在 `src/components/chat/ConversationColumn.vue` 加一行
  `import { MOCK_MERCHANTS } from '@/api/mock/scenarios'`，`npm run lint` 必须失败；
  确认后删除。

---

### Task 9: 真实后端六模式验收与文档同步

**Files:**
- Modify: `docs/frontend-development-plan.md`
- Modify: `docs/project-progress.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Produces: F3 阶段的验收记录与新增文件在项目文档中的登记。

- [ ] **Step 1: 运行完整门禁。**

  Run: `npm run lint; npm run format:check; npm run codegen:check; npm run fixtures:check; npm run mock:check; npm run typecheck; npm run test; npm run test:e2e; npm run build`（工作目录 `frontend/`）

  Expected: 全部退出码为 0。

- [ ] **Step 2: 对着真实后端跑通 P0 六种模式。**

  这是 F3 最可能翻车的地方，必须逐条做。起 b5-b6 后端（Fake LLM），前端
  `VITE_USE_MOCK=false` 启动，依次提问触发 `METRIC`、`DETAIL`、`RULE`、`IDENTITY`、
  `CHAT`、`INVALID` 六种模式各一次。

  Expected: 六条全部渲染出回答正文，**没有一条被 `ChatContractError` 拒掉**。

  `adapters/chat.ts` 的 `semanticGuard` 有一批强断言（降级 CHAT 必须是 `['FALLBACK']`、
  `degraded` 必须带 `degraded_reason`、`quality_attempts ≤ 2`），至今**只被 FakeAgent 的
  fixture 验证过**。真实后端只要有一条组合不同，整条回答会被整个拒掉，表现成
  「接了真实 API 就全线报错」。若发现不一致，先判断是后端产出了不该产出的组合（后端缺陷），
  还是守卫断言过严（前端缺陷），再决定改哪边——不要为了让界面出东西直接放宽守卫。

  逐条结果写入任务报告。

- [ ] **Step 3: 同步项目文档。**

  `docs/frontend-development-plan.md`：勾掉 §F3 任务清单；把 §4 目录树的
  `src/utils/errors.ts` 改为 `src/api/errors.ts` + `src/utils/errorCopy.ts`，
  补入 `src/constants/`；按路线图「文档修订」一节改掉 §F3 相关的失效验收条目。

  `docs/project-progress.md`：更新日期、当前阶段、最近验证、下一步；按 §十七 只写快照。

  `AGENTS.md`：在前端关键路径表中登记 `src/api/errors.ts`、`src/api/credentials.ts`、
  `src/utils/errorCopy.ts`、`src/constants/quickQuestions.ts` 四个新文件的职责。

- [ ] **Step 4: 检查改动范围。**

  Run: `git status; git diff --stat`

  Expected: 改动只落在 `frontend/src/`、`frontend/e2e/`、`frontend/scripts/`、
  `frontend/eslint.config.js`、`frontend/.env.example`、`docs/`、`AGENTS.md`。
  确认没有 `frontend/src/components/insights/**` 的改动——那属于 F4/F5。

  按项目规则不执行 commit。
