# Frontend F2 Mock 会话闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付完整的问答闭环 UI 与状态机——发送、SSE 流式阶段标签、五种消息状态、商家切换与刷新恢复、会话历史与轮次目录——数据来自后端 fixture 镜像，传输层由 Mock 实现。

**Architecture:** Mock 切在传输层。`ChatTransport` 是函数类型，真实实现是 `fetch`，Mock 实现构造 `Response` 并吐出按随机字节边界切块的 SSE 流。其上的 `sse.ts` 解析器、`api/chat.ts` 端点封装、Chat Store 全部走真实代码路径，F3 只替换 transport 实现。fixture 以生成镜像加漂移检查的方式进入前端，与 `docs/api.json` → `generated.ts` → `codegen:check` 对称。

**Tech Stack:** Vue 3、TypeScript、Pinia、Vitest、Vue Test Utils、Playwright、Web Streams API、`@lucide/vue`。

## Global Constraints

- 所有用户可见文案使用中文，代码标识符使用英文。
- **不新增任何运行时依赖**（`package.json` 的 `dependencies` 不得增加条目）。
- 不读取或修改 `docs/api.json`、`src/api/generated.ts`；不改写 `src/api/adapters/chat.ts` 与 `src/types/chat.ts` 中 F0 已交付的部分。
- 组件不直接引用 `generated.ts`，不做字段转换；`snake_case` → `camelCase` 的唯一转换点是 `src/api/adapters/chat.ts`。
- Token 只进内存与请求头，不写 `localStorage`、URL、日志或构建产物；`sessionStorage` 只存 `selected_demo_merchant_key`。
- 前端不得把 `merchant_id` 作为查询参数或请求体字段发给后端。
- 不建登录页，不实现 401/403/409/422 错误码分支（属 F3），不接 ECharts、DETAIL 表格、CSV 导出（属 F4）、反馈（属 F5）、附件（属 F7）。
- 不在 `src/` 应用代码中使用 `@fixtures` 别名——该别名的 TS 路径映射只存在于 `tsconfig.vitest.json`，且 Railway 构建上下文没有 `docs/`。
- 不把 DOM 节点、ECharts 实例或 `File` 对象存入 Store。
- `yshopping-prototype/` 与 `yshopping-merchant-ai 4/` 只读。
- 项目规则禁止未经明确授权的 Git commit/push/tag/PR；本计划的每项以测试通过替代 commit。

**建议的执行断点：** Task 1–8 交付流式问答核心，Task 9–11 交付商家身份与会话历史。在 Task 8 结束处做一次完整门禁与人工试用，再进入 Task 9。

---

### Task 1: fixture 镜像生成与漂移检查

**Files:**
- Create: `frontend/scripts/sync-fixtures.mjs`
- Create: `frontend/scripts/check-fixtures.mjs`
- Create: `frontend/src/api/mock/fixtures.generated.ts`（由脚本生成）
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: `CHAT_FIXTURES: Record<ChatFixtureKey, components['schemas']['ChatResponse']>`，`ChatFixtureKey = 'chatGreeting' | 'invalidRefused' | 'metricGmv' | 'metricOrderDetail' | 'metricRefund' | 'rulePlatform'`。
- Produces: `npm run fixtures`（生成）、`npm run fixtures:check`（漂移检查）。

- [ ] **Step 1: 写生成脚本。**

  `frontend/scripts/sync-fixtures.mjs`：

  ```js
  #!/usr/bin/env node
  /**
   * fixture 镜像生成。
   *
   * 源是 docs/fixtures/chat/*.json（后端 scripts/export_chat_fixtures.py 产出）。
   * Railway 的 frontend service Root Directory 是 /frontend，Docker 构建上下文没有
   * docs/，所以应用代码不能用 @fixtures 别名直接导入源文件，只能消费提交进仓库的镜像。
   *
   * 生成 as const satisfies ChatResponse：JSON 导入会把 answer_mode 推断成 string
   * 而无法满足枚举，as const 可以。于是后端改 schema 时 generated.ts 跟着变，
   * 镜像会在 typecheck 阶段失败，比逐字节比对更早暴露。
   */
  import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
  import { resolve } from 'node:path'
  import { fileURLToPath } from 'node:url'

  const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
  const sourceDir = resolve(frontendRoot, '..', 'docs', 'fixtures', 'chat')
  const outPath = resolve(frontendRoot, 'src', 'api', 'mock', 'fixtures.generated.ts')

  function toCamel(fileName) {
    return fileName.replace(/\.json$/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase())
  }

  export function renderModule() {
    const files = readdirSync(sourceDir).filter((f) => f.endsWith('.json')).sort()
    const entries = files.map((file) => {
      const raw = JSON.parse(readFileSync(resolve(sourceDir, file), 'utf8'))
      return `  ${toCamel(file)}: ${JSON.stringify(raw, null, 2).replace(/\n/g, '\n  ')},`
    })

    return [
      '/* eslint-disable */',
      '/**',
      ' * 本文件由 npm run fixtures 生成，请勿手改。',
      ' * 源：docs/fixtures/chat/*.json（后端 FakeAgent 真实输出）。',
      ' * 漂移检查：npm run fixtures:check。',
      ' */',
      "import type { components } from '@/api/generated'",
      '',
      "type ChatResponse = components['schemas']['ChatResponse']",
      '',
      'export const CHAT_FIXTURES = {',
      ...entries,
      '} as const satisfies Record<string, ChatResponse>',
      '',
      'export type ChatFixtureKey = keyof typeof CHAT_FIXTURES',
      '',
    ].join('\n')
  }

  if (import.meta.url === `file://${process.argv[1]}`.replace(/\\/g, '/')) {
    writeFileSync(outPath, renderModule(), 'utf8')
    console.log(`已生成 ${outPath}`)
  }
  ```

- [ ] **Step 2: 写漂移检查脚本。**

  `frontend/scripts/check-fixtures.mjs`：

  ```js
  #!/usr/bin/env node
  /**
   * fixture 镜像漂移检查。与 check-generated.mjs 同构。
   * 纳入本地质量门禁与 CI，不要纳入 Docker 构建。
   */
  import { readFileSync } from 'node:fs'
  import { resolve } from 'node:path'
  import { fileURLToPath } from 'node:url'

  import { renderModule } from './sync-fixtures.mjs'

  const frontendRoot = resolve(fileURLToPath(new URL('..', import.meta.url)))
  const committedPath = resolve(frontendRoot, 'src', 'api', 'mock', 'fixtures.generated.ts')

  const fresh = renderModule()
  const committed = readFileSync(committedPath, 'utf8')

  if (fresh !== committed) {
    console.error(
      '\nsrc/api/mock/fixtures.generated.ts 与 docs/fixtures/chat/ 不一致。\n' +
        '请运行 npm run fixtures 重新生成并提交。\n' +
        '若 fixture 本身过期，先在 backend/ 运行 uv run python ../scripts/export_chat_fixtures.py。\n',
    )
    process.exit(1)
  }

  console.log('fixtures.generated.ts 与 docs/fixtures/chat/ 一致')
  ```

- [ ] **Step 3: 注册 npm scripts。**

  在 `frontend/package.json` 的 `scripts` 中新增两条，与既有 `codegen` / `codegen:check` 并列：

  ```json
  "fixtures": "node scripts/sync-fixtures.mjs",
  "fixtures:check": "node scripts/check-fixtures.mjs"
  ```

- [ ] **Step 4: 生成镜像并验证。**

  Run: `npm run fixtures; npm run fixtures:check; npm run typecheck`（工作目录 `frontend/`）

  Expected: 三条命令退出码为 0；`src/api/mock/fixtures.generated.ts` 存在且导出六个键。若 `typecheck` 报 `satisfies` 失败，说明 fixture 与 `generated.ts` 真的不一致，先查后端导出而不是改镜像。

---

### Task 2: SSE 解析器

**Files:**
- Create: `frontend/src/api/sse.ts`
- Create: `frontend/src/api/sse.spec.ts`

**Interfaces:**
- Produces: `class SseFrameBuffer { push(text: string): SseFrame[] }`，`interface SseFrame { event: string; data: string }`。
- Produces: `type ChatStreamEvent = { type: 'step'; step: ThinkingStep } | { type: 'done'; raw: RawChatResponse } | { type: 'error'; error: RawErrorResponse }`。
- Produces: `readChatStream(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatStreamEvent>`。
- Produces: `class ChatStreamInterruptedError extends Error`。
- Consumes: `components['schemas']['ChatResponse' | 'ErrorResponse']`、`ThinkingStep`（`@/types/chat`）。

- [ ] **Step 1: 写失败的解析器测试。**

  `frontend/src/api/sse.spec.ts`：

  ```ts
  import { describe, expect, it } from 'vitest'

  import { CHAT_FIXTURES } from './mock/fixtures.generated'
  import { ChatStreamInterruptedError, SseFrameBuffer, readChatStream } from './sse'

  function streamOf(bytes: Uint8Array, sizes: number[]): ReadableStream<Uint8Array> {
    return new ReadableStream<Uint8Array>({
      start(controller) {
        let offset = 0
        let index = 0
        while (offset < bytes.length) {
          const size = sizes[index % sizes.length]
          controller.enqueue(bytes.slice(offset, offset + size))
          offset += size
          index += 1
        }
        controller.close()
      },
    })
  }

  function encodeStream(fixture: (typeof CHAT_FIXTURES)['metricGmv']): Uint8Array {
    let text = ''
    for (const step of fixture.thinking_steps ?? []) {
      text += `event: step\ndata: ${JSON.stringify(step)}\n\n`
    }
    text += ': keep-alive\n\n'
    text += `event: done\ndata: ${JSON.stringify(fixture)}\n\n`
    return new TextEncoder().encode(text)
  }

  describe('SseFrameBuffer', () => {
    it('按空行切分，丢弃注释心跳', () => {
      const buffer = new SseFrameBuffer()

      expect(buffer.push(': keep-alive\n\n')).toEqual([])
      expect(buffer.push('event: step\ndata: {"a":1}\n\n')).toEqual([
        { event: 'step', data: '{"a":1}' },
      ])
    })

    it('一次 push 含多个事件时全部吐出', () => {
      const buffer = new SseFrameBuffer()

      const frames = buffer.push('event: step\ndata: 1\n\nevent: done\ndata: 2\n\n')

      expect(frames).toEqual([
        { event: 'step', data: '1' },
        { event: 'done', data: '2' },
      ])
    })

    it('事件被切成两半时先不吐，凑齐再吐', () => {
      const buffer = new SseFrameBuffer()

      expect(buffer.push('event: step\ndata: {"lab')).toEqual([])
      expect(buffer.push('el":"x"}\n\n')).toEqual([{ event: 'step', data: '{"label":"x"}' }])
    })
  })

  describe('readChatStream', () => {
    // 1 和 3 字节的块必然切断 UTF-8 中文（3 字节/字）和事件边界。
    it.each([[1], [3], [7], [64]])('按 %i 字节切块仍能还原中文与完整载荷', async (size) => {
      const fixture = CHAT_FIXTURES.metricGmv
      const events = []
      for await (const event of readChatStream(streamOf(encodeStream(fixture), [size]))) {
        events.push(event)
      }

      const steps = events.filter((e) => e.type === 'step')
      expect(steps).toHaveLength(fixture.thinking_steps.length)
      expect(steps[0]).toEqual({ type: 'step', step: fixture.thinking_steps[0] })

      const last = events.at(-1)
      expect(last?.type).toBe('done')
      expect(last?.type === 'done' && last.raw.answer).toBe(fixture.answer)
      expect(last?.type === 'done' && last.raw.answer).toContain('昨天总 GMV')
    })

    it('流结束却没有 done 或 error 时抛中断错误', async () => {
      const bytes = new TextEncoder().encode('event: step\ndata: {"label":"x","node":"y"}\n\n')

      await expect(async () => {
        for await (const _ of readChatStream(streamOf(bytes, [5]))) {
          // 只关心迭代结束时的行为
        }
      }).rejects.toThrow(ChatStreamInterruptedError)
    })

    it('error 事件作为终止事件产出，不抛中断错误', async () => {
      const payload = { code: 'INTERNAL_ERROR', message: '演示失败', request_id: 'r1' }
      const bytes = new TextEncoder().encode(`event: error\ndata: ${JSON.stringify(payload)}\n\n`)

      const events = []
      for await (const event of readChatStream(streamOf(bytes, [4]))) {
        events.push(event)
      }

      expect(events).toEqual([{ type: 'error', error: payload }])
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/api/sse.spec.ts`

  Expected: FAIL，因为 `src/api/sse.ts` 尚不存在。

- [ ] **Step 3: 实现解析器。**

  `frontend/src/api/sse.ts`：

  ```ts
  /**
   * SSE 增量解析。
   *
   * 不能用原生 EventSource：聊天请求同时需要 POST、JSON 请求体和 Authorization 头，
   * 三者 EventSource 都不支持（前端方案 §6.1）。
   *
   * 服务端不做分块对齐承诺（后端方案 §8.4），所以必须按字节流累积：一次 read()
   * 可能是半个事件，也可能是多个事件，还可能把一个中文字切成两半。
   */
  import type { components } from '@/api/generated'
  import type { ThinkingStep } from '@/types/chat'

  type RawChatResponse = components['schemas']['ChatResponse']
  type RawErrorResponse = components['schemas']['ErrorResponse']

  export interface SseFrame {
    event: string
    data: string
  }

  export type ChatStreamEvent =
    | { type: 'step'; step: ThinkingStep }
    | { type: 'done'; raw: RawChatResponse }
    | { type: 'error'; error: RawErrorResponse }

  /** 流既没有 done 也没有 error 就结束了。消息必须落到 error，不能永久 streaming。 */
  export class ChatStreamInterruptedError extends Error {
    constructor() {
      super('回答流意外中断，请重试。')
      this.name = 'ChatStreamInterruptedError'
    }
  }

  export class SseFrameBuffer {
    private buffer = ''

    push(text: string): SseFrame[] {
      this.buffer += text
      const frames: SseFrame[] = []

      for (;;) {
        const index = this.buffer.indexOf('\n\n')
        if (index === -1) break

        const raw = this.buffer.slice(0, index)
        this.buffer = this.buffer.slice(index + 2)
        const frame = parseFrame(raw)
        if (frame) frames.push(frame)
      }

      return frames
    }
  }

  function parseFrame(raw: string): SseFrame | null {
    let event = 'message'
    const dataLines: string[] = []

    for (const line of raw.split('\n')) {
      // 以冒号开头的是注释（心跳 `: keep-alive`），不是业务事件。
      if (line.startsWith(':')) continue
      if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim())
    }

    if (dataLines.length === 0) return null
    return { event, data: dataLines.join('\n') }
  }

  // 事件类型只来自 event: 行，不从 data JSON 里再读一个 type 键（后端方案 §8.4）。
  function toStreamEvent(frame: SseFrame): ChatStreamEvent | null {
    if (frame.event === 'step') return { type: 'step', step: JSON.parse(frame.data) }
    if (frame.event === 'done') return { type: 'done', raw: JSON.parse(frame.data) }
    if (frame.event === 'error') return { type: 'error', error: JSON.parse(frame.data) }
    return null
  }

  export async function* readChatStream(
    body: ReadableStream<Uint8Array>,
  ): AsyncGenerator<ChatStreamEvent> {
    const reader = body.getReader()
    // stream: true 是必须的——按块单独解码会让中文在块边界变成乱码。
    const decoder = new TextDecoder('utf-8')
    const frames = new SseFrameBuffer()
    let terminated = false

    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break

        for (const frame of frames.push(decoder.decode(value, { stream: true }))) {
          const event = toStreamEvent(frame)
          if (!event) continue
          if (event.type === 'done' || event.type === 'error') terminated = true
          yield event
        }
      }
    } finally {
      reader.releaseLock()
    }

    if (!terminated) throw new ChatStreamInterruptedError()
  }
  ```

- [ ] **Step 4: 运行测试。**

  Run: `npm run test -- src/api/sse.spec.ts`

  Expected: PASS，共 7 个测试（3 个 buffer + 4 个 stream，其中切块用例参数化 4 次记 4 个）。

---

### Task 3: ChatTransport 与 Mock 传输

**Files:**
- Create: `frontend/src/api/transport.ts`
- Create: `frontend/src/api/mock/scenarios.ts`
- Create: `frontend/src/api/mock/transport.ts`
- Create: `frontend/src/api/mock/transport.spec.ts`
- Modify: `frontend/.env.example`

**Interfaces:**
- Produces: `interface TransportRequest { path: string; method: 'GET' | 'POST' | 'DELETE'; body?: unknown; accept?: string }`。
- Produces: `type ChatTransport = (req: TransportRequest, signal: AbortSignal) => Promise<Response>`。
- Produces: `resolveTransport(): Promise<ChatTransport>`、`setChatTransport(t: ChatTransport | undefined): void`。
- Produces: `createMockTransport(options?: { chunkSizes?: number[]; stepDelayMs?: number }): ChatTransport`。
- Produces: `MOCK_QUICK_QUESTIONS: readonly string[]`、`MOCK_MERCHANTS: readonly components['schemas']['DemoMerchant'][]`。
- Consumes: Task 1 的 `CHAT_FIXTURES`。

- [ ] **Step 1: 写失败的 Mock 传输测试。**

  `frontend/src/api/mock/transport.spec.ts`：

  ```ts
  import { describe, expect, it } from 'vitest'

  import { readChatStream } from '../sse'
  import { MOCK_MERCHANTS, MOCK_QUICK_QUESTIONS } from './scenarios'
  import { createMockTransport } from './transport'

  const transport = createMockTransport({ chunkSizes: [3], stepDelayMs: 0 })

  describe('createMockTransport', () => {
    it('每个快速问题都能命中 fixture 并以 done 收尾', async () => {
      for (const question of MOCK_QUICK_QUESTIONS) {
        const response = await transport(
          {
            path: '/api/chat',
            method: 'POST',
            body: { message: question, client_request_id: 'c1' },
            accept: 'text/event-stream',
          },
          new AbortController().signal,
        )

        const events = []
        for await (const event of readChatStream(response.body!)) events.push(event)

        expect(events.at(-1)?.type, question).toBe('done')
        expect(events.some((e) => e.type === 'step')).toBe(true)
      }
    })

    it('Accept: application/json 时返回普通 JSON，不走流', async () => {
      const response = await transport(
        {
          path: '/api/chat',
          method: 'POST',
          body: { message: '你好', client_request_id: 'c2' },
          accept: 'application/json',
        },
        new AbortController().signal,
      )

      const payload = await response.json()
      expect(payload.answer_mode).toBe('CHAT')
    })

    it('返回演示商家列表，且不含 merchant_id 以外的身份泄漏', async () => {
      const response = await transport(
        { path: '/api/demo/merchants', method: 'GET' },
        new AbortController().signal,
      )

      const payload = await response.json()
      expect(payload.items).toEqual(MOCK_MERCHANTS)
      expect(payload.items.length).toBeGreaterThanOrEqual(2)
    })

    it('已中止的 signal 会让请求以 AbortError 拒绝', async () => {
      const controller = new AbortController()
      controller.abort()

      await expect(
        transport(
          {
            path: '/api/chat',
            method: 'POST',
            body: { message: '你好', client_request_id: 'c3' },
            accept: 'text/event-stream',
          },
          controller.signal,
        ),
      ).rejects.toMatchObject({ name: 'AbortError' })
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/api/mock/transport.spec.ts`

  Expected: FAIL，因为 `scenarios.ts` 与 `transport.ts` 尚不存在。

- [ ] **Step 3: 实现场景映射。**

  `frontend/src/api/mock/scenarios.ts`：

  ```ts
  /**
   * 演示场景。问题文本 → fixture 键。
   *
   * 快速问题必须能命中 fixture，否则点了没反应——F2 验收「每个快速问题均可完成
   * 一轮问答」正是靠这个成立。问题文本取自 docs/fixtures/chat/README.md 记录的
   * 触发问题，与后端 FakeAgent 的判定一致。
   */
  import type { components } from '@/api/generated'

  import type { ChatFixtureKey } from './fixtures.generated'

  interface Scenario {
    question: string
    fixture: ChatFixtureKey
    /** 命中该场景的关键词，任一出现即匹配。 */
    keywords: readonly string[]
  }

  export const MOCK_SCENARIOS: readonly Scenario[] = [
    { question: '昨天总 GMV 是多少？', fixture: 'metricGmv', keywords: ['gmv', '成交额'] },
    { question: '最近7天退货量趋势', fixture: 'metricRefund', keywords: ['退货', '退款'] },
    { question: '查看最近订单明细', fixture: 'metricOrderDetail', keywords: ['明细', '订单列表'] },
    {
      question: '我要货品上架，具体规则有吗？',
      fixture: 'rulePlatform',
      keywords: ['规则', '上架', '政策'],
    },
    { question: '你好', fixture: 'chatGreeting', keywords: ['你好', '在吗', '介绍'] },
    {
      question: '帮我修改订单金额',
      fixture: 'invalidRefused',
      keywords: ['修改订单', '改金额', '删除数据'],
    },
  ] as const

  export const MOCK_QUICK_QUESTIONS = MOCK_SCENARIOS.map((s) => s.question)

  /** 没命中任何关键词时回落到闲聊，与后端 FakeAgent 的兜底一致。 */
  export function matchScenario(message: string): ChatFixtureKey {
    const text = message.toLowerCase()
    const hit = MOCK_SCENARIOS.find(
      (scenario) =>
        scenario.question.toLowerCase() === text ||
        scenario.keywords.some((keyword) => text.includes(keyword)),
    )
    return hit?.fixture ?? 'chatGreeting'
  }

  export const MOCK_MERCHANTS: readonly components['schemas']['DemoMerchant'][] = [
    { merchant_id: 'merchant-100', display_name: 'Borough商家100', token: 'demo-token-100' },
    { merchant_id: 'merchant-101', display_name: 'Borough商家101', token: 'demo-token-101' },
    { merchant_id: 'merchant-102', display_name: 'Borough商家102', token: 'demo-token-102' },
  ] as const
  ```

- [ ] **Step 4: 实现 Mock 传输。**

  `frontend/src/api/mock/transport.ts`：

  ```ts
  /**
   * Mock ChatTransport。
   *
   * 只 mock「传输」：载荷全部是后端 FakeAgent 的真实输出（fixture 镜像），
   * 上层的 sse.ts、Adapter、Store 走的都是真实代码路径。
   *
   * 刻意按小字节块吐出，切断多字节 UTF-8 和事件边界——后端对自己的解析器也是
   * 这么测的（后端方案 §14），前后端对称。
   */
  import type { components } from '@/api/generated'

  import type { ChatTransport, TransportRequest } from '../transport'
  import { CHAT_FIXTURES } from './fixtures.generated'
  import { MOCK_MERCHANTS, matchScenario } from './scenarios'

  type RawChatResponse = components['schemas']['ChatResponse']

  interface MockOptions {
    chunkSizes?: number[]
    stepDelayMs?: number
  }

  function abortError(): Error {
    const error = new Error('请求已取消')
    error.name = 'AbortError'
    return error
  }

  function jsonResponse(payload: unknown, status = 200): Response {
    return new Response(JSON.stringify(payload), {
      status,
      headers: { 'content-type': 'application/json' },
    })
  }

  function encodeSse(fixture: RawChatResponse): Uint8Array {
    let text = ''
    for (const step of fixture.thinking_steps ?? []) {
      text += `event: step\ndata: ${JSON.stringify(step)}\n\n`
    }
    text += ': keep-alive\n\n'
    text += `event: done\ndata: ${JSON.stringify(fixture)}\n\n`
    return new TextEncoder().encode(text)
  }

  function sseResponse(
    fixture: RawChatResponse,
    signal: AbortSignal,
    options: Required<MockOptions>,
  ): Response {
    const bytes = encodeSse(fixture)

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        let offset = 0
        let index = 0

        while (offset < bytes.length) {
          if (signal.aborted) {
            controller.error(abortError())
            return
          }

          const size = options.chunkSizes[index % options.chunkSizes.length]
          controller.enqueue(bytes.slice(offset, offset + size))
          offset += size
          index += 1

          if (options.stepDelayMs > 0) {
            await new Promise((resolve) => setTimeout(resolve, options.stepDelayMs))
          }
        }

        controller.close()
      },
    })

    return new Response(stream, {
      status: 200,
      headers: { 'content-type': 'text/event-stream; charset=utf-8' },
    })
  }

  export function createMockTransport(options: MockOptions = {}): ChatTransport {
    const resolved: Required<MockOptions> = {
      chunkSizes: options.chunkSizes ?? [5, 13, 3, 29, 7],
      stepDelayMs: options.stepDelayMs ?? 12,
    }

    // 每个 transport 实例持有自己的会话表。放模块级会让状态在测试之间泄漏，
    // 「删除后列表为空」这类断言就会依赖测试执行顺序。
    const conversations = new Map<
      string,
      {
        id: string
        title: string
        createdAt: string
        messages: components['schemas']['ConversationMessage'][]
      }
    >()

    return async (request: TransportRequest, signal: AbortSignal): Promise<Response> => {
      if (signal.aborted) throw abortError()

      if (request.path === '/api/demo/merchants') {
        // 契约里这个键是 merchants，不是 items——与 ConversationListResponse 不同。
        return jsonResponse({
          merchants: MOCK_MERCHANTS,
        } satisfies components['schemas']['DemoMerchantListResponse'])
      }

      if (request.path === '/api/chat' && request.method === 'POST') {
        const body = request.body as { message: string; session_id?: string | null }
        const fixture = CHAT_FIXTURES[matchScenario(body.message)] as RawChatResponse
        const sessionId = body.session_id ?? fixture.session_id
        const now = new Date().toISOString()
        const answerId = crypto.randomUUID()

        const existing = conversations.get(sessionId)
        const record = existing ?? {
          id: sessionId,
          title: body.message.slice(0, 20),
          createdAt: now,
          messages: [],
        }
        // 记下真实往返，历史会话点开才有内容可载入。
        record.messages.push(
          { id: crypto.randomUUID(), role: 'user', content: body.message, created_at: now },
          { id: answerId, role: 'assistant', content: fixture.answer, created_at: now },
        )
        conversations.set(sessionId, record)

        const payload = { ...fixture, session_id: sessionId, id: answerId }

        if (request.accept === 'application/json') return jsonResponse(payload)
        return sseResponse(payload, signal, resolved)
      }

      if (request.path === '/api/conversations' && request.method === 'GET') {
        const items = [...conversations.values()].map((item) => ({
          id: item.id,
          title: item.title,
          created_at: item.createdAt,
          updated_at: item.createdAt,
        }))
        return jsonResponse({ items, limit: 20, offset: 0 })
      }

      const detailMatch = /^\/api\/conversations\/([^/]+)$/.exec(request.path)
      if (detailMatch) {
        const id = detailMatch[1]
        if (request.method === 'DELETE') {
          conversations.delete(id)
          return new Response(null, { status: 204 })
        }

        const found = conversations.get(id)
        if (!found) return jsonResponse({ code: 'NOT_FOUND', message: '会话不存在' }, 404)

        return jsonResponse({
          id: found.id,
          title: found.title,
          messages: found.messages,
          created_at: found.createdAt,
          updated_at: found.createdAt,
        })
      }

      return jsonResponse({ code: 'NOT_FOUND', message: `Mock 未覆盖 ${request.path}` }, 404)
    }
  }
  ```

- [ ] **Step 5: 实现 transport 选择器。**

  `frontend/src/api/transport.ts`：

  ```ts
  /**
   * 传输层。Mock 与真实实现的唯一分叉点。
   *
   * F2 只提供 Mock 分支；F3 在此补真实 fetch、鉴权头装配和错误码分支，
   * 上层（sse.ts、api/chat.ts、Store）一行都不用改。
   *
   * Mock 走动态 import 且由环境变量守卫，生产构建不包含 fixture 镜像。
   */
  export interface TransportRequest {
    path: string
    method: 'GET' | 'POST' | 'DELETE'
    body?: unknown
    accept?: string
  }

  export type ChatTransport = (req: TransportRequest, signal: AbortSignal) => Promise<Response>

  let override: ChatTransport | undefined
  let cached: ChatTransport | undefined

  /** 测试注入用。传 undefined 恢复默认解析。 */
  export function setChatTransport(transport: ChatTransport | undefined): void {
    override = transport
    cached = undefined
  }

  export function isMockEnabled(): boolean {
    return import.meta.env.VITE_USE_MOCK === 'true'
  }

  export async function resolveTransport(): Promise<ChatTransport> {
    if (override) return override
    if (cached) return cached

    if (!isMockEnabled()) {
      throw new Error(
        '真实传输层将在 F3 提供。当前请设置 VITE_USE_MOCK=true 使用演示数据。',
      )
    }

    const { createMockTransport } = await import('./mock/transport')
    cached = createMockTransport()
    return cached
  }
  ```

- [ ] **Step 6: 补环境变量样例。**

  在 `frontend/.env.example` 追加：

  ```text
  # F2 使用 Mock 传输层与后端 fixture 演示数据；F3 接入真实 API 后置为 false。
  VITE_USE_MOCK=true
  ```

  同时在 `frontend/.env.development` 设置 `VITE_USE_MOCK=true`（若该文件不存在则创建，并保留既有的 `VITE_API_BASE_URL`）。

- [ ] **Step 7: 运行测试。**

  Run: `npm run test -- src/api/mock/transport.spec.ts src/api/sse.spec.ts`

  Expected: PASS。

---

### Task 4: 端点封装 api/chat.ts

**Files:**
- Create: `frontend/src/api/chat.ts`
- Create: `frontend/src/api/chat.spec.ts`

**Interfaces:**
- Produces: `submitChat(input: { message: string; sessionId?: string; clientRequestId: string }, handlers: { onStep(step: ThinkingStep): void }, signal: AbortSignal): Promise<ChatAnswer>`。
- Produces: `listConversations(signal: AbortSignal): Promise<ConversationSummaryView[]>`，`ConversationSummaryView = { id: string; title: string; createdAt: string; updatedAt: string }`。
- Produces: `getConversation(id: string, signal: AbortSignal): Promise<ConversationDetailView>`，`ConversationDetailView = { id: string; title: string; messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; createdAt: string }> }`。
- Produces: `deleteConversation(id: string, signal: AbortSignal): Promise<void>`。
- Produces: `listDemoMerchants(signal: AbortSignal): Promise<DemoMerchantView[]>`，`DemoMerchantView = { merchantId: string; displayName: string; token: string }`。
- Consumes: Task 2 的 `readChatStream`、Task 3 的 `resolveTransport`、F0 的 `toChatAnswer`。

- [ ] **Step 1: 写失败的端点测试。**

  `frontend/src/api/chat.spec.ts`：

  ```ts
  import { afterEach, describe, expect, it, vi } from 'vitest'

  import { listConversations, listDemoMerchants, submitChat } from './chat'
  import { createMockTransport } from './mock/transport'
  import { setChatTransport } from './transport'

  setChatTransport(createMockTransport({ chunkSizes: [3], stepDelayMs: 0 }))

  afterEach(() => {
    setChatTransport(createMockTransport({ chunkSizes: [3], stepDelayMs: 0 }))
  })

  describe('submitChat', () => {
    it('推进 step 回调并返回经 Adapter 的领域模型', async () => {
      const onStep = vi.fn()

      const answer = await submitChat(
        { message: '昨天总 GMV 是多少？', clientRequestId: 'c1' },
        { onStep },
        new AbortController().signal,
      )

      expect(onStep).toHaveBeenCalled()
      expect(onStep.mock.calls[0][0]).toHaveProperty('label')
      expect(answer.mode).toBe('METRIC')
      expect(answer.metric?.displayName).toBeTruthy()
      expect(answer.answer).toContain('GMV')
    })

    it('请求体携带 client_request_id 且不含 merchant_id', async () => {
      const seen: unknown[] = []
      setChatTransport(async (request, signal) => {
        seen.push(request.body)
        return createMockTransport({ chunkSizes: [8], stepDelayMs: 0 })(request, signal)
      })

      await submitChat(
        { message: '你好', clientRequestId: 'c2' },
        { onStep: () => {} },
        new AbortController().signal,
      )

      expect(seen[0]).toMatchObject({ message: '你好', client_request_id: 'c2' })
      expect(JSON.stringify(seen[0])).not.toContain('merchant_id')
    })
  })

  describe('会话与商家端点', () => {
    it('提交后能在会话列表里看到该会话', async () => {
      await submitChat(
        { message: '你好', clientRequestId: 'c3' },
        { onStep: () => {} },
        new AbortController().signal,
      )

      const items = await listConversations(new AbortController().signal)

      expect(items.length).toBeGreaterThanOrEqual(1)
      expect(items[0]).toHaveProperty('createdAt')
    })

    it('演示商家转换为 camelCase 视图模型', async () => {
      const merchants = await listDemoMerchants(new AbortController().signal)

      expect(merchants[0]).toMatchObject({ merchantId: 'merchant-100', displayName: 'Borough商家100' })
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/api/chat.spec.ts`

  Expected: FAIL，因为 `src/api/chat.ts` 尚不存在。

- [ ] **Step 3: 实现端点封装。**

  `frontend/src/api/chat.ts`：

  ```ts
  /**
   * 四个业务端点的调用封装。
   *
   * 组件与 Store 只调这里，不直接碰 transport 或 generated.ts。
   * SSE 的 done 载荷与非流式响应完全一致，所以两条路径共用同一个 Adapter
   * （后端方案 §8.4：只写一套解析逻辑）。
   */
  import type { components } from '@/api/generated'
  import type { ChatAnswer, ThinkingStep } from '@/types/chat'

  import { toChatAnswer } from './adapters/chat'
  import { ChatStreamInterruptedError, readChatStream } from './sse'
  import { resolveTransport } from './transport'

  export interface ConversationSummaryView {
    id: string
    title: string
    createdAt: string
    updatedAt: string
  }

  export interface DemoMerchantView {
    merchantId: string
    displayName: string
    token: string
  }

  export interface SubmitChatInput {
    message: string
    sessionId?: string
    clientRequestId: string
  }

  export interface SubmitChatHandlers {
    onStep(step: ThinkingStep): void
  }

  /** 流内 error 事件。与 HTTP 层错误分开：后者在 F3 才有码分支。 */
  export class ChatStreamError extends Error {
    constructor(message: string) {
      super(message)
      this.name = 'ChatStreamError'
    }
  }

  export async function submitChat(
    input: SubmitChatInput,
    handlers: SubmitChatHandlers,
    signal: AbortSignal,
  ): Promise<ChatAnswer> {
    const transport = await resolveTransport()
    const response = await transport(
      {
        path: '/api/chat',
        method: 'POST',
        // 只发契约里的字段。merchant_id 由服务端从 Token 解析，前端不传。
        body: {
          message: input.message,
          session_id: input.sessionId ?? null,
          client_request_id: input.clientRequestId,
        },
        accept: 'text/event-stream',
      },
      signal,
    )

    if (!response.body) throw new ChatStreamInterruptedError()

    let answer: ChatAnswer | undefined
    for await (const event of readChatStream(response.body)) {
      if (event.type === 'step') handlers.onStep(event.step)
      else if (event.type === 'error') throw new ChatStreamError(event.error.message)
      else answer = toChatAnswer(event.raw)
    }

    if (!answer) throw new ChatStreamInterruptedError()
    return answer
  }

  export async function listConversations(signal: AbortSignal): Promise<ConversationSummaryView[]> {
    const transport = await resolveTransport()
    const response = await transport({ path: '/api/conversations', method: 'GET' }, signal)
    const payload = (await response.json()) as components['schemas']['ConversationListResponse']

    return payload.items.map((item) => ({
      id: item.id,
      title: item.title ?? '未命名会话',
      createdAt: item.created_at,
      updatedAt: item.updated_at,
    }))
  }

  export interface ConversationDetailView {
    id: string
    title: string
    messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; createdAt: string }>
  }

  export async function getConversation(
    id: string,
    signal: AbortSignal,
  ): Promise<ConversationDetailView> {
    const transport = await resolveTransport()
    const response = await transport({ path: `/api/conversations/${id}`, method: 'GET' }, signal)
    const payload = (await response.json()) as components['schemas']['ConversationDetailResponse']

    return {
      id: payload.id,
      title: payload.title ?? '未命名会话',
      messages: payload.messages.map((item) => ({
        id: item.id,
        role: item.role === 'user' ? 'user' : 'assistant',
        content: item.content,
        createdAt: item.created_at,
      })),
    }
  }

  export async function deleteConversation(id: string, signal: AbortSignal): Promise<void> {
    const transport = await resolveTransport()
    await transport({ path: `/api/conversations/${id}`, method: 'DELETE' }, signal)
  }

  export async function listDemoMerchants(signal: AbortSignal): Promise<DemoMerchantView[]> {
    const transport = await resolveTransport()
    const response = await transport({ path: '/api/demo/merchants', method: 'GET' }, signal)
    const payload = (await response.json()) as components['schemas']['DemoMerchantListResponse']

    // 注意键名是 merchants；会话列表用的才是 items。
    return payload.merchants.map((item) => ({
      merchantId: item.merchant_id,
      displayName: item.display_name,
      token: item.token,
    }))
  }
  ```

- [ ] **Step 4: 运行测试。**

  Run: `npm run test -- src/api/chat.spec.ts`

  Expected: PASS。

---

### Task 5: Chat Store 消息状态机

**Files:**
- Modify: `frontend/src/types/chat.ts`（追加 `MessageStatus` 与 `ChatMessage`）
- Modify: `frontend/src/stores/chat.ts`
- Create: `frontend/src/stores/chat.spec.ts`

**Interfaces:**
- Produces: `type MessageStatus = 'pending' | 'streaming' | 'complete' | 'cancelled' | 'error'`。
- Produces: `interface ChatMessage { localId: string; id?: string; clientRequestId: string; role: 'user' | 'assistant'; text: string; createdAt: string; status: MessageStatus; steps: ThinkingStep[]; errorMessage?: string; answer?: ChatAnswer }`。
- Produces: `useChatStore()` 暴露 `messages`、`sessionId`、`selectedRoundId`、`isEmptyConversation`、`currentAnswer`、`submitMessage(text)`、`reset()`。
- Consumes: Task 4 的 `submitChat`。

- [ ] **Step 1: 追加领域类型。**

  在 `frontend/src/types/chat.ts` 末尾追加（不改动 F0 已有内容）：

  ```ts
  /**
   * 消息状态。cancelled 与 error 刻意分开：用户主动取消不是故障，
   * UI 文案与是否提示重试都不同，混在一起会让每次取消都弹一次「出错了」。
   */
  export type MessageStatus = 'pending' | 'streaming' | 'complete' | 'cancelled' | 'error'

  export interface ChatMessage {
    localId: string
    id?: string
    /** 幂等键。入列时生成并常驻，重试路径直接从消息对象拿（前端方案 §5.9）。 */
    clientRequestId: string
    role: 'user' | 'assistant'
    text: string
    createdAt: string
    status: MessageStatus
    steps: ThinkingStep[]
    errorMessage?: string
    answer?: ChatAnswer
  }
  ```

- [ ] **Step 2: 写失败的 Store 测试。**

  `frontend/src/stores/chat.spec.ts`：

  ```ts
  import { createPinia, setActivePinia } from 'pinia'
  import { beforeEach, describe, expect, it } from 'vitest'

  import { createMockTransport } from '@/api/mock/transport'
  import { setChatTransport } from '@/api/transport'

  import { useChatStore } from './chat'

  beforeEach(() => {
    setActivePinia(createPinia())
    setChatTransport(createMockTransport({ chunkSizes: [4], stepDelayMs: 0 }))
  })

  describe('useChatStore', () => {
    it('发送后用户与助手消息各一条，助手落到 complete', async () => {
      const store = useChatStore()

      await store.submitMessage('昨天总 GMV 是多少？')

      expect(store.messages).toHaveLength(2)
      expect(store.messages[0]).toMatchObject({ role: 'user', text: '昨天总 GMV 是多少？' })
      expect(store.messages[1].role).toBe('assistant')
      expect(store.messages[1].status).toBe('complete')
      expect(store.isEmptyConversation).toBe(false)
    })

    it('助手消息累积 step 事件并保存回答', async () => {
      const store = useChatStore()

      await store.submitMessage('昨天总 GMV 是多少？')

      const assistant = store.messages[1]
      expect(assistant.steps.length).toBeGreaterThan(0)
      expect(assistant.answer?.mode).toBe('METRIC')
      expect(assistant.answer?.metric?.displayName).toBeTruthy()
    })

    it('用户消息与助手消息共享同一个 clientRequestId', async () => {
      const store = useChatStore()

      await store.submitMessage('你好')

      expect(store.messages[1].clientRequestId).toBe(store.messages[0].clientRequestId)
      expect(store.messages[0].clientRequestId).not.toHaveLength(0)
    })

    it('空白输入不入列', async () => {
      const store = useChatStore()

      await store.submitMessage('   ')

      expect(store.messages).toHaveLength(0)
    })

    it('reset 清空消息、会话与选中轮次', async () => {
      const store = useChatStore()
      await store.submitMessage('你好')

      store.reset()

      expect(store.messages).toEqual([])
      expect(store.sessionId).toBeUndefined()
      expect(store.selectedRoundId).toBeUndefined()
      expect(store.isEmptyConversation).toBe(true)
    })

    it('选中轮次决定 currentAnswer，不受后续轮次影响', async () => {
      const store = useChatStore()
      await store.submitMessage('昨天总 GMV 是多少？')
      const firstRound = store.messages[1].localId
      await store.submitMessage('我要货品上架，具体规则有吗？')

      expect(store.currentAnswer?.mode).toBe('RULE')
      store.selectRound(firstRound)
      expect(store.currentAnswer?.mode).toBe('METRIC')
    })
  })
  ```

- [ ] **Step 3: 运行测试确认失败。**

  Run: `npm run test -- src/stores/chat.spec.ts`

  Expected: FAIL，因为 Store 还只有 F1 的 `isEmptyConversation` 与 `reset`。

- [ ] **Step 4: 实现 Store。**

  `frontend/src/stores/chat.ts` 整体替换为：

  ```ts
  import { computed, ref } from 'vue'
  import { defineStore } from 'pinia'

  import { submitChat } from '@/api/chat'
  import type { ChatAnswer, ChatMessage, ThinkingStep } from '@/types/chat'

  function newMessage(
    role: ChatMessage['role'],
    text: string,
    clientRequestId: string,
    status: ChatMessage['status'],
  ): ChatMessage {
    return {
      localId: crypto.randomUUID(),
      clientRequestId,
      role,
      text,
      createdAt: new Date().toISOString(),
      status,
      steps: [],
    }
  }

  export const useChatStore = defineStore('chat', () => {
    const messages = ref<ChatMessage[]>([])
    const sessionId = ref<string | undefined>(undefined)
    const selectedRoundId = ref<string | undefined>(undefined)
    const controllers = new Map<string, AbortController>()

    const isEmptyConversation = computed(() => messages.value.length === 0)

    const assistantRounds = computed(() =>
      messages.value.filter((message) => message.role === 'assistant'),
    )

    const currentAnswer = computed<ChatAnswer | undefined>(() => {
      const target =
        assistantRounds.value.find((message) => message.localId === selectedRoundId.value) ??
        assistantRounds.value.at(-1)
      return target?.answer
    })

    function selectRound(localId: string): void {
      selectedRoundId.value = localId
    }

    function reset(): void {
      for (const controller of controllers.values()) controller.abort()
      controllers.clear()
      messages.value = []
      sessionId.value = undefined
      selectedRoundId.value = undefined
    }

    async function runRound(assistant: ChatMessage, text: string): Promise<void> {
      const controller = new AbortController()
      controllers.set(assistant.localId, controller)

      try {
        const answer = await submitChat(
          {
            message: text,
            sessionId: sessionId.value,
            clientRequestId: assistant.clientRequestId,
          },
          {
            onStep(step: ThinkingStep) {
              // 第一个 step 到达即进入 streaming，这是「1 秒内可见处理状态」的落点。
              assistant.status = 'streaming'
              assistant.steps.push(step)
            },
          },
          controller.signal,
        )

        assistant.answer = answer
        assistant.id = answer.id
        assistant.text = answer.answer
        assistant.status = 'complete'
        sessionId.value = answer.sessionId
        selectedRoundId.value = assistant.localId
      } catch (error) {
        const name = (error as Error).name
        assistant.status = name === 'AbortError' ? 'cancelled' : 'error'
        assistant.errorMessage =
          name === 'AbortError' ? '已取消本次回答。' : (error as Error).message
      } finally {
        controllers.delete(assistant.localId)
      }
    }

    async function submitMessage(text: string): Promise<void> {
      const content = text.trim()
      if (!content) return

      const clientRequestId = crypto.randomUUID()
      const user = newMessage('user', content, clientRequestId, 'complete')
      const assistant = newMessage('assistant', '', clientRequestId, 'pending')
      messages.value.push(user, assistant)

      await runRound(assistant, content)
    }

    return {
      messages,
      sessionId,
      selectedRoundId,
      isEmptyConversation,
      assistantRounds,
      currentAnswer,
      submitMessage,
      selectRound,
      reset,
    }
  })
  ```

- [ ] **Step 5: 运行测试。**

  Run: `npm run test -- src/stores/chat.spec.ts`

  Expected: PASS，6 个测试。

---

### Task 6: 取消、重试与流中断

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/stores/chat.spec.ts`

**Interfaces:**
- Produces: `useChatStore()` 追加 `cancelMessage(localId: string): void`、`retryMessage(localId: string): Promise<void>`、`isBusy: boolean`。

- [ ] **Step 1: 追加失败的测试。**

  在 `frontend/src/stores/chat.spec.ts` 末尾追加：

  ```ts
  describe('取消与重试', () => {
    it('取消会中断底层流并置为 cancelled，不是 error', async () => {
      setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
      const store = useChatStore()

      const pending = store.submitMessage('昨天总 GMV 是多少？')
      await new Promise((resolve) => setTimeout(resolve, 10))
      store.cancelMessage(store.messages[1].localId)
      await pending

      expect(store.messages[1].status).toBe('cancelled')
      expect(store.messages[1].errorMessage).toContain('已取消')
    })

    it('重试复用原 clientRequestId', async () => {
      setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
      const store = useChatStore()

      const pending = store.submitMessage('你好')
      await new Promise((resolve) => setTimeout(resolve, 10))
      store.cancelMessage(store.messages[1].localId)
      await pending
      const original = store.messages[1].clientRequestId

      setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
      await store.retryMessage(store.messages[1].localId)

      expect(store.messages[1].clientRequestId).toBe(original)
      expect(store.messages[1].status).toBe('complete')
      expect(store.messages).toHaveLength(2)
    })

    it('流没有 done 也没有 error 时落到 error，不停在 streaming', async () => {
      setChatTransport(async () => {
        const bytes = new TextEncoder().encode(
          'event: step\ndata: {"label":"正在识别问题","node":"classify"}\n\n',
        )
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(bytes)
              controller.close()
            },
          }),
        )
      })
      const store = useChatStore()

      await store.submitMessage('你好')

      expect(store.messages[1].status).toBe('error')
      expect(store.messages[1].errorMessage).toContain('中断')
    })

    it('重试不累加阶段标签，而是重新开始计数', async () => {
      setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
      const store = useChatStore()
      await store.submitMessage('你好')
      const firstRun = store.messages[1].steps.length

      await store.retryMessage(store.messages[1].localId)

      expect(firstRun).toBeGreaterThan(0)
      // 若 retryMessage 忘了清空 steps，这里会是 firstRun * 2。
      expect(store.messages[1].steps).toHaveLength(firstRun)
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/stores/chat.spec.ts`

  Expected: FAIL，`cancelMessage` 与 `retryMessage` 未定义。

- [ ] **Step 3: 实现取消与重试。**

  在 `frontend/src/stores/chat.ts` 的 `submitMessage` 之后追加，并把两个新动作加入 return：

  ```ts
    const isBusy = computed(() =>
      messages.value.some(
        (message) => message.status === 'pending' || message.status === 'streaming',
      ),
    )

    function cancelMessage(localId: string): void {
      // 真正中断底层流，不只是 UI 上隐藏——否则后端会继续跑完并计费。
      controllers.get(localId)?.abort()
    }

    async function retryMessage(localId: string): Promise<void> {
      const assistant = messages.value.find((message) => message.localId === localId)
      if (!assistant || assistant.role !== 'assistant') return

      const questionIndex = messages.value.findIndex((message) => message.localId === localId) - 1
      const question = messages.value[questionIndex]
      if (!question) return

      // 复用原 clientRequestId：后端据此可能直接返回已完成结果，避免重复计费（§5.9）。
      assistant.status = 'pending'
      assistant.errorMessage = undefined
      assistant.steps = []

      await runRound(assistant, question.text)
    }
  ```

  return 块改为：

  ```ts
    return {
      messages,
      sessionId,
      selectedRoundId,
      isEmptyConversation,
      isBusy,
      assistantRounds,
      currentAnswer,
      submitMessage,
      retryMessage,
      cancelMessage,
      selectRound,
      reset,
    }
  ```

- [ ] **Step 4: 运行测试。**

  Run: `npm run test -- src/stores/chat.spec.ts`

  Expected: PASS，10 个测试。

---

### Task 7: 消息渲染与输入区接线

**Files:**
- Create: `frontend/src/components/chat/ChatMessage.vue`
- Create: `frontend/src/components/chat/ChatMessage.spec.ts`
- Modify: `frontend/src/components/chat/ConversationColumn.vue`
- Modify: `frontend/src/components/chat/ConversationColumn.spec.ts`

**Interfaces:**
- Produces: `ChatMessage.vue` props `message: ChatMessageModel`，事件 `retry`、`cancel`、`select`。
- Produces: `ConversationColumn.vue` 消费 `useChatStore()`，渲染快速问题、消息列表与阶段标签。
- Consumes: Task 3 的 `MOCK_QUICK_QUESTIONS`、Task 5/6 的 Store 动作。

- [ ] **Step 1: 写失败的组件测试。**

  `frontend/src/components/chat/ChatMessage.spec.ts`：

  ```ts
  import { mount } from '@vue/test-utils'
  import { describe, expect, it } from 'vitest'

  import type { ChatMessage as ChatMessageModel } from '@/types/chat'

  import ChatMessage from './ChatMessage.vue'

  function makeMessage(overrides: Partial<ChatMessageModel> = {}): ChatMessageModel {
    return {
      localId: 'm1',
      clientRequestId: 'c1',
      role: 'assistant',
      text: '',
      createdAt: '2026-08-03T00:00:00Z',
      status: 'pending',
      steps: [],
      ...overrides,
    }
  }

  describe('ChatMessage', () => {
    it('streaming 时展示最新阶段标签', () => {
      const wrapper = mount(ChatMessage, {
        props: {
          message: makeMessage({
            status: 'streaming',
            steps: [
              { label: '识别商家与业务意图', node: 'classify' },
              { label: '读取业务口径并整理演示数据', node: 'compose' },
            ],
          }),
        },
      })

      expect(wrapper.get('[data-testid="stage-label"]').text()).toBe('读取业务口径并整理演示数据')
    })

    it('error 时提供重试入口', async () => {
      const wrapper = mount(ChatMessage, {
        props: { message: makeMessage({ status: 'error', errorMessage: '回答流意外中断，请重试。' }) },
      })

      await wrapper.get('[data-testid="retry-button"]').trigger('click')

      expect(wrapper.emitted('retry')).toEqual([['m1']])
      expect(wrapper.text()).toContain('回答流意外中断')
    })

    it('cancelled 的文案与 error 不同，且不说「出错」', () => {
      const wrapper = mount(ChatMessage, {
        props: { message: makeMessage({ status: 'cancelled', errorMessage: '已取消本次回答。' }) },
      })

      expect(wrapper.text()).toContain('已取消')
      expect(wrapper.text()).not.toContain('出错')
    })

    it('streaming 时提供取消入口', async () => {
      const wrapper = mount(ChatMessage, {
        props: { message: makeMessage({ status: 'streaming', steps: [{ label: '识别', node: 'c' }] }) },
      })

      await wrapper.get('[data-testid="cancel-button"]').trigger('click')

      expect(wrapper.emitted('cancel')).toEqual([['m1']])
    })
  })
  ```

  `frontend/src/components/chat/ConversationColumn.spec.ts` 整体替换为：

  ```ts
  import { mount } from '@vue/test-utils'
  import { createPinia, setActivePinia } from 'pinia'
  import { beforeEach, describe, expect, it } from 'vitest'

  import { createMockTransport } from '@/api/mock/transport'
  import { setChatTransport } from '@/api/transport'
  import { useChatStore } from '@/stores/chat'

  import ChatComposer from './ChatComposer.vue'
  import ConversationColumn from './ConversationColumn.vue'

  beforeEach(() => {
    setActivePinia(createPinia())
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  })

  describe('ConversationColumn', () => {
    it('组合独立的 ChatComposer 与可滚动消息区域', () => {
      const wrapper = mount(ConversationColumn)

      expect(wrapper.findComponent(ChatComposer).exists()).toBe(true)
      expect(wrapper.find('[data-testid="chat-list"]').exists()).toBe(true)
    })

    it('空会话时展示快速问题，点击即完成一轮问答', async () => {
      const wrapper = mount(ConversationColumn)
      const store = useChatStore()

      const quick = wrapper.get('[data-testid="quick-question"]')
      const text = quick.text()
      await quick.trigger('click')
      await new Promise((resolve) => setTimeout(resolve, 0))

      expect(store.messages[0].text).toBe(text)
      expect(store.messages[1].status).toBe('complete')
    })

    it('有消息后不再展示空状态', async () => {
      const wrapper = mount(ConversationColumn)
      const store = useChatStore()

      await store.submitMessage('你好')
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[data-testid="quick-question"]').exists()).toBe(false)
      expect(wrapper.findAll('[data-testid="chat-message"]')).toHaveLength(2)
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/components/chat/ChatMessage.spec.ts src/components/chat/ConversationColumn.spec.ts`

  Expected: FAIL，`ChatMessage.vue` 不存在且 `ConversationColumn.vue` 未接 Store。

- [ ] **Step 3: 实现消息组件。**

  `frontend/src/components/chat/ChatMessage.vue`：

  ```vue
  <script setup lang="ts">
  import { Loader, RotateCcw, Square } from '@lucide/vue'
  import { computed } from 'vue'

  import type { ChatMessage as ChatMessageModel } from '@/types/chat'

  const props = defineProps<{ message: ChatMessageModel }>()

  const emit = defineEmits<{
    retry: [localId: string]
    cancel: [localId: string]
    select: [localId: string]
  }>()

  const latestStage = computed(() => props.message.steps.at(-1)?.label ?? '正在准备')
  const isRunning = computed(
    () => props.message.status === 'pending' || props.message.status === 'streaming',
  )
  </script>

  <template>
    <article
      class="chat-message"
      :class="`chat-message--${message.role}`"
      data-testid="chat-message"
      @click="emit('select', message.localId)"
    >
      <div v-if="isRunning" class="chat-message__stage" role="status" aria-live="polite">
        <Loader class="chat-message__spinner" :size="14" aria-hidden="true" />
        <span data-testid="stage-label">{{ latestStage }}</span>
        <button type="button" data-testid="cancel-button" @click.stop="emit('cancel', message.localId)">
          <Square :size="12" aria-hidden="true" />
          <span>停止</span>
        </button>
      </div>

      <p v-else-if="message.status === 'cancelled'" class="chat-message__notice">
        {{ message.errorMessage }}
        <button type="button" data-testid="retry-button" @click.stop="emit('retry', message.localId)">
          <RotateCcw :size="12" aria-hidden="true" />
          <span>重新回答</span>
        </button>
      </p>

      <p v-else-if="message.status === 'error'" class="chat-message__notice chat-message__notice--error">
        {{ message.errorMessage }}
        <button type="button" data-testid="retry-button" @click.stop="emit('retry', message.localId)">
          <RotateCcw :size="12" aria-hidden="true" />
          <span>重试</span>
        </button>
      </p>

      <p v-else class="chat-message__text">{{ message.text }}</p>
    </article>
  </template>

  <style scoped>
  .chat-message {
    padding: var(--space-3) var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-card);
    background: #fff;
    box-shadow: var(--shadow-control);
  }

  .chat-message--user {
    border-color: #cdd7fd;
    background: var(--color-primary-soft);
  }

  .chat-message__text {
    margin: 0;
    color: var(--color-text);
    font-size: var(--font-size-body);
    line-height: 1.6;
    white-space: pre-wrap;
  }

  .chat-message__stage,
  .chat-message__notice {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-meta);
  }

  .chat-message__notice--error {
    color: var(--color-danger-text);
  }

  .chat-message__stage button,
  .chat-message__notice button {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    padding: 3px var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-small);
    color: var(--color-text-secondary);
    background: var(--color-surface);
    font-size: var(--font-size-meta);
  }

  .chat-message__spinner {
    animation: chat-message-spin 1s linear infinite;
  }

  @keyframes chat-message-spin {
    to {
      transform: rotate(360deg);
    }
  }
  </style>
  ```

  注意：F1 复查整改已把字号纳入 tokens。若 `--font-size-body` / `--font-size-meta` 在 `tokens.css` 中不存在，先补入 tokens 再引用，不要在组件里硬编码 px。

- [ ] **Step 4: 接线 ConversationColumn。**

  `frontend/src/components/chat/ConversationColumn.vue` 的 `<script setup>` 与消息区改为：

  ```vue
  <script setup lang="ts">
  import { Sparkles } from '@lucide/vue'

  import { MOCK_QUICK_QUESTIONS } from '@/api/mock/scenarios'
  import { useChatStore } from '@/stores/chat'

  import ChatComposer from './ChatComposer.vue'
  import ChatMessage from './ChatMessage.vue'

  const chatStore = useChatStore()

  function ask(text: string): void {
    void chatStore.submitMessage(text)
  }
  </script>
  ```

  模板中 `conversation-column__list` 内部改为：欢迎卡保持不变；空状态卡片在 `chatStore.isEmptyConversation` 为真时渲染，并在其中列出快速问题按钮；否则渲染消息列表。Composer 的 `@submit` 接 `ask`。

  ```vue
      <section v-if="chatStore.isEmptyConversation" class="empty-card">
        <span>开始一段新会话</span>
        <p>输入经营问题后，这里会呈现分析过程、结论和行动建议。</p>
        <ul class="quick-questions">
          <li v-for="question in MOCK_QUICK_QUESTIONS" :key="question">
            <button type="button" data-testid="quick-question" @click="ask(question)">
              {{ question }}
            </button>
          </li>
        </ul>
      </section>

      <ChatMessage
        v-for="message in chatStore.messages"
        v-else
        :key="message.localId"
        :message="message"
        @retry="chatStore.retryMessage"
        @cancel="chatStore.cancelMessage"
        @select="chatStore.selectRound"
      />
  ```

  `v-else` 不能和 `v-for` 写在同一元素上——把消息列表包进一个 `<template v-else>` 再在内部 `v-for`。

  ```vue
      <template v-else>
        <ChatMessage
          v-for="message in chatStore.messages"
          :key="message.localId"
          :message="message"
          @retry="chatStore.retryMessage"
          @cancel="chatStore.cancelMessage"
          @select="chatStore.selectRound"
        />
      </template>
  ```

  并把 `<ChatComposer @submit="emit('submit', $event)" />` 改为 `<ChatComposer @submit="ask" />`，同时删除组件自身的 `defineEmits`——中列不再向上冒泡，直接驱动 Store。

- [ ] **Step 5: 运行测试。**

  Run: `npm run test -- src/components/chat/`

  Expected: PASS。

---

### Task 8: 侧栏三面板

**Files:**
- Create: `frontend/src/components/insights/MetricDefinitionPanel.vue`
- Create: `frontend/src/components/insights/MetricChartPanel.vue`
- Create: `frontend/src/components/insights/RecommendationPanel.vue`
- Create: `frontend/src/components/insights/InsightPanels.spec.ts`
- Modify: `frontend/src/views/AssistantView.vue`

**Interfaces:**
- Produces: 三个组件均接收 `answer?: ChatAnswer`。
- Produces: `RecommendationPanel` 事件 `ask(question: string)`。

- [ ] **Step 1: 写失败的面板测试。**

  `frontend/src/components/insights/InsightPanels.spec.ts`：

  ```ts
  import { mount } from '@vue/test-utils'
  import { describe, expect, it } from 'vitest'

  import { toChatAnswer } from '@/api/adapters/chat'
  import { CHAT_FIXTURES } from '@/api/mock/fixtures.generated'
  import type { components } from '@/api/generated'

  import MetricChartPanel from './MetricChartPanel.vue'
  import MetricDefinitionPanel from './MetricDefinitionPanel.vue'
  import RecommendationPanel from './RecommendationPanel.vue'

  const metricAnswer = toChatAnswer(CHAT_FIXTURES.metricGmv as components['schemas']['ChatResponse'])
  const ruleAnswer = toChatAnswer(CHAT_FIXTURES.rulePlatform as components['schemas']['ChatResponse'])

  describe('MetricDefinitionPanel', () => {
    it('展示口径、来源、负责人与状态', () => {
      const wrapper = mount(MetricDefinitionPanel, { props: { answer: metricAnswer } })

      expect(wrapper.text()).toContain(metricAnswer.metric!.displayName)
      expect(wrapper.text()).toContain(metricAnswer.metric!.source)
      expect(wrapper.text()).toContain(metricAnswer.metric!.owner)
    })

    it('RULE 模式没有指标时显示空状态而不是零值', () => {
      const wrapper = mount(MetricDefinitionPanel, { props: { answer: ruleAnswer } })

      expect(wrapper.find('[data-testid="metric-empty"]').exists()).toBe(true)
      expect(wrapper.text()).not.toContain('undefined')
    })
  })

  describe('MetricChartPanel', () => {
    it('有图表数据时只展示 F4 占位说明，不渲染画布', () => {
      const wrapper = mount(MetricChartPanel, { props: { answer: metricAnswer } })

      expect(wrapper.get('[data-testid="chart-placeholder"]').text()).toContain('F4')
      expect(wrapper.find('canvas').exists()).toBe(false)
    })
  })

  describe('RecommendationPanel', () => {
    it('展示建议三要素并可直接发送猜你想问', async () => {
      const wrapper = mount(RecommendationPanel, { props: { answer: metricAnswer } })

      const first = metricAnswer.recommendations[0]
      expect(wrapper.text()).toContain(first.title)
      expect(wrapper.text()).toContain(first.evidence)
      expect(wrapper.text()).toContain(first.action)

      await wrapper.get('[data-testid="suggested-question"]').trigger('click')
      expect(wrapper.emitted('ask')?.[0]?.[0]).toBe(metricAnswer.suggestions.current[0])
    })

    it('没有回答时显示空状态', () => {
      const wrapper = mount(RecommendationPanel, { props: { answer: undefined } })

      expect(wrapper.find('[data-testid="recommendation-empty"]').exists()).toBe(true)
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/components/insights/InsightPanels.spec.ts`

  Expected: FAIL，三个组件均不存在。

- [ ] **Step 3: 实现三个面板。**

  `MetricDefinitionPanel.vue` 渲染 `answer?.metric` 的 `displayName`、`definition`、`source`、`owner`、`status`；`status === 'UNVERIFIED'` 时加一条醒目的待核验提示。`answer?.metric` 为 `undefined` 时渲染 `data-testid="metric-empty"` 的空状态。

  `MetricChartPanel.vue` 在 `answer?.chart?.enabled` 为真时渲染 `data-testid="chart-placeholder"`，文案写明「图表将在 F4 呈现」并列出 `chart.title` 与数据点条数；否则渲染空状态。**不引入 ECharts。**

  `RecommendationPanel.vue` 渲染 `answer.recommendations` 的 `title` / `evidence` / `action` 三要素，以及 `answer.suggestions.current` 的问题按钮（`data-testid="suggested-question"`），点击 `emit('ask', question)`。`answer` 为空时渲染 `data-testid="recommendation-empty"`。

  三个组件统一使用 tokens，不硬编码 px；小字号说明文本的对比度必须达到 WCAG AA（F1 复查整改已定的基线）。

- [ ] **Step 4: 接入 AssistantView。**

  `frontend/src/views/AssistantView.vue` 左侧 `<aside>` 内改为 `<MetricDefinitionPanel :answer="chatStore.currentAnswer" />` 与 `<MetricChartPanel :answer="chatStore.currentAnswer" />`；右侧 `<aside>` 内改为 `<RecommendationPanel :answer="chatStore.currentAnswer" @ask="chatStore.submitMessage" />`。保留 `aria-label` 与 `data-testid="workspace-column"`。

- [ ] **Step 5: 运行测试与门禁。**

  Run: `npm run lint; npm run format:check; npm run fixtures:check; npm run codegen:check; npm run typecheck; npm run test; npm run build`

  Expected: 全部退出码为 0。这是流式核心的完整门禁，通过后再进入 Task 9。

---

### Task 9: Auth Store 与商家身份

**Files:**
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/stores/auth.spec.ts`
- Modify: `frontend/src/views/AssistantView.vue`
- Modify: `frontend/src/views/AssistantView.spec.ts`

**Interfaces:**
- Produces: `useAuthStore()` 暴露 `merchants: DemoMerchantView[]`、`selected?: DemoMerchantView`、`displayNames: string[]`、`loadMerchants()`、`selectByDisplayName(name: string)`、`restore()`。
- Consumes: Task 4 的 `listDemoMerchants`。

- [ ] **Step 1: 写失败的 Auth Store 测试。**

  `frontend/src/stores/auth.spec.ts`：

  ```ts
  import { createPinia, setActivePinia } from 'pinia'
  import { beforeEach, describe, expect, it } from 'vitest'

  import { createMockTransport } from '@/api/mock/transport'
  import { setChatTransport } from '@/api/transport'

  import { MERCHANT_STORAGE_KEY, useAuthStore } from './auth'

  beforeEach(() => {
    setActivePinia(createPinia())
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    sessionStorage.clear()
  })

  describe('useAuthStore', () => {
    it('加载商家列表并默认选中第一个', async () => {
      const store = useAuthStore()

      await store.loadMerchants()

      expect(store.merchants.length).toBeGreaterThanOrEqual(2)
      expect(store.selected?.displayName).toBe('Borough商家100')
    })

    it('选中商家只把非敏感标识写入 sessionStorage，Token 不落盘', async () => {
      const store = useAuthStore()
      await store.loadMerchants()

      store.selectByDisplayName('Borough商家101')

      expect(sessionStorage.getItem(MERCHANT_STORAGE_KEY)).toBe('merchant-101')
      expect(JSON.stringify(sessionStorage)).not.toContain('demo-token')
      expect(JSON.stringify(localStorage)).not.toContain('demo-token')
    })

    it('restore 用持久化标识选回同一商家', async () => {
      sessionStorage.setItem(MERCHANT_STORAGE_KEY, 'merchant-102')
      const store = useAuthStore()

      await store.restore()

      expect(store.selected?.displayName).toBe('Borough商家102')
      expect(store.selected?.token).toBe('demo-token-102')
    })

    it('标识在列表中找不到时回退默认商家并给出提示', async () => {
      sessionStorage.setItem(MERCHANT_STORAGE_KEY, 'merchant-999')
      const store = useAuthStore()

      await store.restore()

      expect(store.selected?.merchantId).toBe('merchant-100')
      expect(store.restoreNotice).toContain('重新选择')
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/stores/auth.spec.ts`

  Expected: FAIL，`src/stores/auth.ts` 不存在。

- [ ] **Step 3: 实现 Auth Store。**

  `frontend/src/stores/auth.ts`：

  ```ts
  import { computed, ref } from 'vue'
  import { defineStore } from 'pinia'

  import { listDemoMerchants, type DemoMerchantView } from '@/api/chat'

  /**
   * 只持久化非敏感的商家标识。Token 仅进内存与请求头，
   * 不写 localStorage、URL、日志或构建产物（前端方案 §6.2）。
   */
  export const MERCHANT_STORAGE_KEY = 'selected_demo_merchant_key'

  export const useAuthStore = defineStore('auth', () => {
    const merchants = ref<DemoMerchantView[]>([])
    const selected = ref<DemoMerchantView | undefined>(undefined)
    const restoreNotice = ref('')

    const displayNames = computed(() => merchants.value.map((item) => item.displayName))

    async function loadMerchants(): Promise<void> {
      merchants.value = await listDemoMerchants(new AbortController().signal)
      if (!selected.value) selected.value = merchants.value[0]
    }

    function select(merchant: DemoMerchantView): void {
      selected.value = merchant
      sessionStorage.setItem(MERCHANT_STORAGE_KEY, merchant.merchantId)
    }

    function selectByDisplayName(displayName: string): void {
      const found = merchants.value.find((item) => item.displayName === displayName)
      if (found) select(found)
    }

    async function restore(): Promise<void> {
      await loadMerchants()
      const key = sessionStorage.getItem(MERCHANT_STORAGE_KEY)
      if (!key) return

      const found = merchants.value.find((item) => item.merchantId === key)
      if (found) {
        select(found)
        return
      }

      restoreNotice.value = '上次使用的演示商家已不可用，请重新选择商家。'
      if (merchants.value[0]) select(merchants.value[0])
    }

    return { merchants, selected, displayNames, restoreNotice, loadMerchants, selectByDisplayName, restore }
  })
  ```

- [ ] **Step 4: 接入 AssistantView。**

  `AssistantView.vue` 删除硬编码的 `merchantOptions` 与 `selectedMerchant`，改为 `onMounted(() => void authStore.restore())`；`MerchantSwitcher` 的 `:merchants="authStore.displayNames"`、`:model-value="authStore.selected?.displayName ?? ''"`，`@update:model-value` 处理器改为先 `authStore.selectByDisplayName(name)` 再 `chatStore.reset()`——且仅在名称确实变化时才 reset，保留 F1 整改已定的行为。列表为空时切换器展示「加载中」。

  `AssistantView.spec.ts` 中「选择演示商家后更新顶栏中可见的商家名」一例需在 `beforeEach` 注入 Mock transport 并 `await` 列表加载后再断言。

- [ ] **Step 5: 运行测试。**

  Run: `npm run test -- src/stores/auth.spec.ts src/views/AssistantView.spec.ts`

  Expected: PASS。

---

### Task 10: 会话历史与轮次目录

**Files:**
- Create: `frontend/src/components/chat/ConversationNav.vue`
- Create: `frontend/src/components/layout/ConversationDrawer.vue`
- Create: `frontend/src/components/layout/ConversationDrawer.spec.ts`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/views/AssistantView.vue`

**Interfaces:**
- Produces: `useChatStore()` 追加 `conversations: ConversationSummaryView[]`、`loadConversations()`、`loadConversation(id: string)`、`removeConversation(id: string)`。
- Produces: `ConversationNav.vue` props `rounds: ChatMessageModel[]`、`selectedId?: string`，事件 `select`。
- Produces: `ConversationDrawer.vue` props `open: boolean`，事件 `close`、`delete`。

- [ ] **Step 1: 写失败的抽屉测试。**

  `frontend/src/components/layout/ConversationDrawer.spec.ts`：

  ```ts
  import { mount } from '@vue/test-utils'
  import { createPinia, setActivePinia } from 'pinia'
  import { beforeEach, describe, expect, it } from 'vitest'

  import { createMockTransport } from '@/api/mock/transport'
  import { setChatTransport } from '@/api/transport'
  import { useChatStore } from '@/stores/chat'

  import ConversationDrawer from './ConversationDrawer.vue'

  beforeEach(() => {
    setActivePinia(createPinia())
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  })

  describe('ConversationDrawer', () => {
    it('列出已有会话并可删除', async () => {
      const store = useChatStore()
      await store.submitMessage('你好')
      await store.loadConversations()

      const wrapper = mount(ConversationDrawer, { props: { open: true } })
      expect(wrapper.findAll('[data-testid="conversation-item"]')).toHaveLength(1)

      await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
      await new Promise((resolve) => setTimeout(resolve, 0))

      expect(store.conversations).toHaveLength(0)
    })

    it('点击会话把历史消息载入当前会话', async () => {
      const store = useChatStore()
      await store.submitMessage('昨天总 GMV 是多少？')
      await store.loadConversations()
      const conversationId = store.conversations[0].id
      store.reset()

      const wrapper = mount(ConversationDrawer, { props: { open: true } })
      await wrapper.get('[data-testid="conversation-open"]').trigger('click')
      await new Promise((resolve) => setTimeout(resolve, 0))

      expect(store.sessionId).toBe(conversationId)
      expect(store.messages).toHaveLength(2)
      expect(store.messages[0].text).toBe('昨天总 GMV 是多少？')
      expect(store.messages[0].status).toBe('complete')
    })

    it('open 为 false 时不渲染内容', () => {
      const wrapper = mount(ConversationDrawer, { props: { open: false } })

      expect(wrapper.find('[data-testid="conversation-item"]').exists()).toBe(false)
    })

    it('Escape 关闭抽屉', async () => {
      const wrapper = mount(ConversationDrawer, { props: { open: true } })

      await wrapper.get('[data-testid="drawer-panel"]').trigger('keydown', { key: 'Escape' })

      expect(wrapper.emitted('close')).toBeTruthy()
    })
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/components/layout/ConversationDrawer.spec.ts`

  Expected: FAIL。

- [ ] **Step 3: 扩展 Store。**

  在 `frontend/src/stores/chat.ts` 中追加，并加入 return：

  ```ts
    const conversations = ref<ConversationSummaryView[]>([])

    async function loadConversations(): Promise<void> {
      conversations.value = await listConversations(new AbortController().signal)
    }

    async function loadConversation(id: string): Promise<void> {
      const detail = await getConversation(id, new AbortController().signal)

      reset()
      sessionId.value = detail.id
      // 历史消息没有流式过程，直接落到终态；answer 留空，侧栏因此显示空状态而不是
      // 上一轮的残留——重新提问才会有完整回答载荷。
      messages.value = detail.messages.map((item) => ({
        localId: crypto.randomUUID(),
        id: item.id,
        clientRequestId: crypto.randomUUID(),
        role: item.role,
        text: item.content,
        createdAt: item.createdAt,
        status: 'complete' as const,
        steps: [],
      }))
    }

    async function removeConversation(id: string): Promise<void> {
      await deleteConversation(id, new AbortController().signal)
      conversations.value = conversations.value.filter((item) => item.id !== id)
      // 删掉的正是当前会话时，回到空会话，避免界面停在已不存在的数据上。
      if (sessionId.value === id) reset()
    }
  ```

  同步补 import：`import { deleteConversation, getConversation, listConversations, submitChat, type ConversationSummaryView } from '@/api/chat'`。

  注意 `loadConversation` 先调 `reset()` 再赋值——`reset()` 会清空 `sessionId`，顺序反了会把刚设好的会话 ID 抹掉。

- [ ] **Step 4: 实现两个组件并接入页面。**

  `ConversationNav.vue` 渲染 `rounds` 的序号与问题摘要，点击 `emit('select', localId)`，当前项加 `aria-current="true"`。放在 `ConversationColumn` 顶部，消息数大于等于两轮时才显示。

  `ConversationDrawer.vue` 在 `open` 为真时渲染一个带 `role="dialog"`、`aria-label="历史会话"`、`data-testid="drawer-panel"` 且 `tabindex="-1"` 的面板，列出 `chatStore.conversations`（`data-testid="conversation-item"`）。每项含两个按钮：标题按钮 `data-testid="conversation-open"` 调 `chatStore.loadConversation(id)` 并 `emit('close')`；删除按钮 `data-testid="conversation-delete"` 调 `chatStore.removeConversation(id)`，删除按钮需 `@click.stop` 以免同时触发载入。`keydown.esc` 触发 `close`。打开时把焦点移入面板，关闭时归还给触发按钮——F1 整改已为商家菜单建立同样的焦点归还模式，沿用它。

  `AssistantView.vue` 把 F1 顶栏那个 `aria-label="打开对话目录"` 的按钮接上抽屉开关，并删除其 `title="对话目录将在后续版本提供"`（功能已提供）。挂载时调用 `chatStore.loadConversations()`。

- [ ] **Step 5: 运行测试。**

  Run: `npm run test -- src/components/ src/stores/`

  Expected: PASS。

---

### Task 11: E2E 与文档同步

**Files:**
- Create: `frontend/e2e/conversation.spec.ts`
- Modify: `frontend/e2e/assistant.spec.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: `docs/frontend-development-plan.md`
- Modify: `docs/project-progress.md`

- [ ] **Step 1: 确保 E2E 以 Mock 模式启动。**

  在 `frontend/playwright.config.ts` 的 `webServer` 配置中显式注入 `env: { VITE_USE_MOCK: 'true' }`，保证 E2E 不依赖真实后端。

- [ ] **Step 2: 编写会话闭环 E2E。**

  `frontend/e2e/conversation.spec.ts` 覆盖：

  ```ts
  import { expect, test } from '@playwright/test'

  test('点击快速问题可完成一轮问答，阶段标签先于回答出现', async ({ page }) => {
    await page.goto('/')

    const quick = page.getByTestId('quick-question').first()
    const question = await quick.textContent()
    await quick.click()

    await expect(page.getByTestId('stage-label')).toBeVisible({ timeout: 1000 })
    await expect(page.getByTestId('chat-message').first()).toContainText(question!.trim())
    await expect(page.getByTestId('chat-message')).toHaveCount(2)
  })

  test('连续两轮后目录含两个节点，点击可切换侧栏内容', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('quick-question').first().click()
    await expect(page.getByTestId('chat-message')).toHaveCount(2)

    await page.getByLabel('输入问题').fill('我要货品上架，具体规则有吗？')
    await page.getByLabel('发送问题').click()
    await expect(page.getByTestId('chat-message')).toHaveCount(4)

    await expect(page.getByTestId('conversation-nav-item')).toHaveCount(2)
    await page.getByTestId('conversation-nav-item').first().click()
    await expect(page.getByTestId('metric-empty')).toBeHidden()
  })

  test('切换商家清空会话与侧栏', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('quick-question').first().click()
    await expect(page.getByTestId('chat-message')).toHaveCount(2)

    await page.getByLabel('切换当前演示商家').click()
    await page.locator('[role="option"][data-merchant="Borough商家101"]').click()

    await expect(page.getByTestId('chat-message')).toHaveCount(0)
    await expect(page.getByTestId('quick-question').first()).toBeVisible()
  })

  test('刷新后选回同一商家', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('切换当前演示商家').click()
    await page.locator('[role="option"][data-merchant="Borough商家102"]').click()

    await page.reload()

    await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家102')
  })

  test('停止按钮真正中断本轮，且文案不说「出错」', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('输入问题').fill('最近7天退货量趋势')
    await page.getByLabel('发送问题').click()

    await page.getByTestId('cancel-button').click()

    await expect(page.getByTestId('chat-message').nth(1)).toContainText('已取消')
    await expect(page.getByTestId('chat-message').nth(1)).not.toContainText('出错')
    await expect(page.getByTestId('stage-label')).toHaveCount(0)
  })

  test('跨 560px 断点调整窗口后选中商家不丢失', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 900 })
    await page.goto('/')
    await page.getByLabel('切换当前演示商家').click()
    await page.locator('[role="option"][data-merchant="Borough商家101"]').click()

    await page.setViewportSize({ width: 420, height: 900 })
    await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家101')

    await page.setViewportSize({ width: 900, height: 900 })
    await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家101')
  })

  test('删除会话后列表同步移除', async ({ page }) => {
    await page.goto('/')
    await page.getByTestId('quick-question').first().click()
    await expect(page.getByTestId('chat-message')).toHaveCount(2)

    await page.getByLabel('打开对话目录').click()
    await expect(page.getByTestId('conversation-item')).toHaveCount(1)
    await page.getByTestId('conversation-delete').first().click()

    await expect(page.getByTestId('conversation-item')).toHaveCount(0)
  })
  ```

  `ConversationNav.vue` 的条目需带 `data-testid="conversation-nav-item"`。

- [ ] **Step 3: 补充无控制台错误覆盖。**

  在 `frontend/e2e/assistant.spec.ts` 的首个测试中，于断言之前补一次快速问题点击与回答完成的等待，确保流式路径也在「无控制台错误」的覆盖范围内。

- [ ] **Step 4: 运行全量门禁。**

  Run: `npm run lint; npm run format:check; npm run fixtures:check; npm run codegen:check; npm run typecheck; npm run test; npm run test:e2e; npm run build`

  Expected: 全部退出码为 0。

- [ ] **Step 5: 验证生产构建不含 Mock。**

  Run: `npm run build` 后检索产物：`grep -rl "昨天总 GMV" dist/ || echo "生产产物不含 fixture"`（`VITE_USE_MOCK` 未设为 `true` 的构建）

  Expected: 输出「生产产物不含 fixture」。若命中，说明动态 import 的守卫失效，需修正 `resolveTransport` 而不是删测试。

- [ ] **Step 6: 文档同步。**

  在 `docs/frontend-development-plan.md` §F2 中把已由 F0/F1 完成的三条任务标注为已完成并注明阶段（领域模型与 Adapter 属 F0；`ConversationColumn` / `ChatComposer` / `MerchantSwitcher` 创建与 Enter 发送属 F1），把 `components/insights/` 与 `components/layout/ConversationDrawer.vue` 补入 §4 目录树。

  在 `docs/project-progress.md` 更新当前阶段、已完成、最近验证与下一步，写明 F2 的自动化结果与 Mock 边界，并记录「`api/chat.ts` 已在 F2 建立，F3 只替换 transport 与错误处理，不重复创建」。
