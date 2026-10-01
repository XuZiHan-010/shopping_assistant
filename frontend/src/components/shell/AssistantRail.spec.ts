/**
 * 助手栏（W Task 6）。挂载真实路由表与外壳：助手栏常驻 `MerchantShell` 的
 * `#assistant-rail`，这里从 `/?assistant=open`（`/ops-assistant` 旧地址的落点）进入，
 * 逐条承接原 `OpsAssistantView.spec.ts` 的断言（映射表见 W Task 6 报告）。
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { useOpsChatStore } from '@/stores/opsChat'
import { useRailStore } from '@/stores/rail'

const BASE_URL = 'http://127.0.0.1:8000'
const LIST = 'GET /api/v2/merchant/conversations'
const CHAT = 'POST /api/v2/merchant/chat'
const SESSIONS = 'POST /api/v2/merchant/sessions'

type Handler = (body?: unknown) => Response

function json(payload: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function answer(conversationId: string, text: string, overrides: Record<string, unknown> = {}) {
  return {
    id: `a-${conversationId}`,
    conversation_id: conversationId,
    answer: text,
    tool_calls: [],
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    quality_status: 'PASSED',
    quality_attempts: 1,
    degraded: false,
    degraded_reason: null,
    created_at: '2026-09-24T00:00:01Z',
    answer_mode: 'MERCHANT_OPS',
    ...overrides,
  }
}

function sse(text: string): Response {
  return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

function turnStream(conversationId: string, text: string, overrides: Record<string, unknown> = {}) {
  return sse(
    `event: turn_complete\ndata: ${JSON.stringify(answer(conversationId, text, overrides))}\n\n`,
  )
}

function summary(id: string, title: string) {
  return { id, title, created_at: '2026-09-24T00:00:00Z', updated_at: '2026-09-24T00:00:00Z' }
}

function page(items: unknown[]) {
  return { items, next_cursor: null, has_more: false }
}

function session(suffix = '0', name = 'Borough商家100') {
  return json(
    {
      session_id: 'sid'.padEnd(43, suffix),
      role: 'MERCHANT',
      expires_at: '2099-01-01T00:00:00Z',
      merchant_display_name: name,
    },
    201,
  )
}

function routeFetch(table: Record<string, Handler>) {
  const seen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${(init?.method ?? 'GET').toUpperCase()} ${new URL(String(input)).pathname}`
      seen.push(key)
      const handler = table[key]
      if (!handler) throw new Error(`未登记的路由：${key}`)
      return handler(typeof init?.body === 'string' ? JSON.parse(init.body) : undefined)
    }),
  )
  return { seen, count: (key: string) => seen.filter((k) => k === key).length }
}

const mounted: VueWrapper[] = []

async function mountApp(router: Router, pinia: ReturnType<typeof createPinia>) {
  // `MetricChartPanel` 是异步组件；真正走动态 import() 会在测试环境拆除后才 resolve。
  // stub 掉，只验证「是否挂载」，内部渲染由 `InsightPanels.spec.ts` 覆盖。
  const wrapper = mount(
    { template: '<RouterView />' },
    {
      attachTo: document.body,
      global: {
        plugins: [pinia, i18n, router],
        stubs: { MetricChartPanel: { template: '<section data-test="ops-chart" />' } },
      },
    },
  )
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

/** 已选中商家、已有会话，从 `/?assistant=open` 进入。 */
async function mountRail(
  table: Record<string, Handler>,
  options: { before?: () => void; path?: string } = {},
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(session()))
  await auth.openSession(auth.merchants[0]!)
  options.before?.()
  const backend = routeFetch(table)
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push(options.path ?? '/?assistant=open')
  await router.isReady()
  const wrapper = await mountApp(router, pinia)
  return { wrapper, backend, router, auth }
}

type Wrapper = Awaited<ReturnType<typeof mountRail>>['wrapper']

async function ask(wrapper: Wrapper, text: string) {
  await wrapper.get('[data-test=ops-input]').setValue(text)
  await wrapper.get('[data-test=ops-form]').trigger('submit')
  await flushPromises()
}

async function showHistory(wrapper: Wrapper) {
  await wrapper.get('[data-test=rail-history-toggle]').trigger('click')
  await flushPromises()
}

function isShown(wrapper: Wrapper, selector: string): boolean {
  const element = wrapper.get(selector).element as HTMLElement
  return element.style.display !== 'none' && !element.closest('[hidden]')
}

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  i18n.global.locale.value = 'zh-CN'
})
afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('AssistantRail 助手栏', () => {
  // ---------------- 开合与入口 ----------------

  it('/?assistant=open 打开助手栏，并只从地址里去掉 assistant 参数', async () => {
    const { wrapper, router } = await mountRail(
      { [LIST]: () => json(page([])) },
      { path: '/?assistant=open&from=memory' },
    )

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-rail')).toBe('open')
    expect(wrapper.get('#assistant-rail').attributes('hidden')).toBeUndefined()
    expect(router.currentRoute.value.name).toBe('home')
    expect(router.currentRoute.value.query).toEqual({ from: 'memory' })
  })

  it('/ops-assistant?conversation=… 打开助手栏并打开这段对话，conversation 参数保留', async () => {
    const { wrapper, router, backend } = await mountRail(
      {
        [LIST]: () => json(page([summary('c-7', '上周的对话')])),
        'GET /api/v2/merchant/conversations/c-7': () =>
          json({
            conversation: summary('c-7', '上周的对话'),
            messages: page([
              {
                id: 'm-1',
                role: 'user',
                content: '上周的提问',
                created_at: '2026-09-24T00:00:01Z',
                answer: null,
                feedback: null,
              },
            ]),
          }),
      },
      { path: '/ops-assistant?conversation=c-7' },
    )

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-rail')).toBe('open')
    expect(backend.count('GET /api/v2/merchant/conversations/c-7')).toBe(1)
    expect(wrapper.get('.ops-view__log').text()).toContain('上周的提问')
    expect(router.currentRoute.value.fullPath).toBe('/?conversation=c-7')
  })

  it('收起时不拉会话目录；第一次打开才拉', async () => {
    const { wrapper, backend } = await mountRail({ [LIST]: () => json(page([])) }, { path: '/' })

    expect(wrapper.get('#assistant-rail').attributes('hidden')).toBeDefined()
    expect(backend.count(LIST)).toBe(0)

    useRailStore().show()
    await flushPromises()
    expect(backend.count(LIST)).toBe(1)
  })

  it('历史面板开着时发送问题，切回对话面板看回答', async () => {
    const { wrapper } = await mountRail({
      [CHAT]: () => turnStream('c-1', '回答'),
      [LIST]: () => json(page([])),
    })
    await showHistory(wrapper)

    await ask(wrapper, '问题')

    expect(isShown(wrapper, '#assistant-rail-history')).toBe(false)
    expect(wrapper.get('.ops-view__log').text()).toContain('回答')
  })

  it('头部「收起」按钮关闭助手栏', async () => {
    const { wrapper } = await mountRail({ [LIST]: () => json(page([])) })

    await wrapper.get('[data-test=rail-close]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-rail')).toBe('closed')
  })

  it('打开时焦点移到输入框', async () => {
    const { wrapper } = await mountRail({ [LIST]: () => json(page([])) }, { path: '/' })

    useRailStore().show()
    await flushPromises()

    expect(document.activeElement).toBe(wrapper.get('[data-test=ops-input]').element)
  })

  // ---------------- 问助手：只填不发 ----------------

  it('简报预填的问题只填入输入框，不自动发送', async () => {
    const { wrapper, backend } = await mountRail(
      { [LIST]: () => json(page([])) },
      { before: () => useOpsChatStore().prefill('给「测试商品」起草一份补货草稿') },
    )
    const input = wrapper.get('[data-test=ops-input]').element as HTMLTextAreaElement
    expect(input.value).toBe('给「测试商品」起草一份补货草稿')
    expect(backend.count(CHAT)).toBe(0)
  })

  it('页面上的「问助手」（rail.ask）预填并打开收起的助手栏，不发送', async () => {
    const { wrapper, backend } = await mountRail({ [LIST]: () => json(page([])) }, { path: '/' })

    useRailStore().ask('请查看售后事项 sale-1')
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-rail')).toBe('open')
    const input = wrapper.get('[data-test=ops-input]').element as HTMLTextAreaElement
    expect(input.value).toBe('请查看售后事项 sale-1')
    expect(backend.count(CHAT)).toBe(0)
  })

  it('历史面板开着时「问助手」切回对话面板', async () => {
    const { wrapper } = await mountRail({ [LIST]: () => json(page([])) })
    await showHistory(wrapper)
    expect(isShown(wrapper, '#assistant-rail-history')).toBe(true)

    useRailStore().ask('哪些商品快卖完了？')
    await flushPromises()

    expect(isShown(wrapper, '#assistant-rail-history')).toBe(false)
    expect(isShown(wrapper, '[data-test=ops-input]')).toBe(true)
  })

  it('猜你想问点击后填入输入框，不代为发送', async () => {
    const { wrapper, backend } = await mountRail({
      [CHAT]: () => turnStream('c-1', '好的', { suggestions: ['哪些商品快卖完了？'] }),
      [LIST]: () => json(page([summary('c-1', '你好')])),
    })
    await ask(wrapper, '你好')
    await wrapper.get('[data-test=ops-suggestion]').trigger('click')
    const input = wrapper.get('[data-test=ops-input]').element as HTMLTextAreaElement
    expect(input.value).toBe('哪些商品快卖完了？')
    expect(backend.count(CHAT)).toBe(1)
  })

  it('输入法选词时按回车不发送；普通回车发送', async () => {
    const { wrapper, backend } = await mountRail({
      [CHAT]: () => turnStream('c-1', '好的'),
      [LIST]: () => json(page([summary('c-1', 'kucun')])),
    })
    const input = wrapper.get('[data-test=ops-input]')
    await input.setValue('kucun')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    await flushPromises()
    expect(backend.count(CHAT)).toBe(0)

    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(backend.count(CHAT)).toBe(1)
  })

  // ---------------- 回答：反馈、降级、工具步骤、图表 ----------------

  it('当前回答可采纳、赞踩并填写原因；按 v2 kind 提交且显示回执', async () => {
    const requests: unknown[] = []
    let adopted = false
    const { wrapper } = await mountRail({
      [CHAT]: () => turnStream('c-1', '回答'),
      [LIST]: () => json(page([])),
      'POST /api/v2/merchant/answers/a-c-1/feedback': (body) => {
        requests.push(body)
        const input = body as Record<string, unknown>
        if (input.kind === 'ADOPTION') adopted = input.adopted as boolean
        return json({
          answer_id: 'a-c-1',
          adopted,
          reaction: input.kind === 'REACTION' ? input.reaction : null,
          reason: input.kind === 'REACTION' ? (input.reason ?? null) : null,
          updated_at: '2026-09-24T00:00:02Z',
        })
      },
    })
    await ask(wrapper, '问题')
    const bubble = wrapper.get('[data-test=ops-feedback]')
    await bubble.get('[data-test=ops-adopt]').trigger('click')
    await flushPromises()
    await bubble.get('[data-test=ops-reason]').setValue('  很有帮助  ')
    await bubble.get('[data-test=ops-like]').trigger('click')
    await flushPromises()
    expect(requests).toEqual([
      { client_request_id: expect.any(String), kind: 'ADOPTION', adopted: true },
      {
        client_request_id: expect.any(String),
        kind: 'REACTION',
        reaction: 'LIKE',
        reason: '很有帮助',
      },
    ])
    expect(bubble.get('[data-test=ops-adopt]').attributes('aria-pressed')).toBe('true')
    expect(bubble.get('[data-test=ops-like]').attributes('aria-pressed')).toBe('true')
    expect(bubble.get('[data-test=ops-feedback-status]').text()).toContain('已记录')
  })

  it('历史回答也有反馈入口；失败显示错误并可重试', async () => {
    let fail = true
    const { wrapper } = await mountRail({
      [LIST]: () => json(page([summary('c-1', '旧对话')])),
      'GET /api/v2/merchant/conversations/c-1': () =>
        json({
          conversation: summary('c-1', '旧对话'),
          messages: page([
            {
              id: 'm-1',
              role: 'assistant',
              content: '旧回答',
              created_at: '2026-09-24T00:00:01Z',
              answer: answer('c-1', '旧回答'),
              feedback: { adopted: true, reaction: 'LIKE', reason: '此前有帮助' },
            },
          ]),
        }),
      'POST /api/v2/merchant/answers/a-c-1/feedback': () => {
        if (fail)
          return json(
            {
              code: 'DATA_SOURCE_UNAVAILABLE',
              message: '暂时不可用',
              request_id: 'r',
              details: [],
              retryable: true,
            },
            503,
          )
        return json({
          answer_id: 'a-c-1',
          adopted: true,
          reaction: null,
          reason: null,
          updated_at: '2026-09-24T00:00:02Z',
        })
      },
    })
    await showHistory(wrapper)
    await wrapper.get('[data-test=ops-conversation-open]').trigger('click')
    await flushPromises()
    const bubble = wrapper.get('[data-test=ops-feedback]')
    expect(bubble.get('[data-test=ops-adopt]').attributes('aria-pressed')).toBe('true')
    expect(bubble.get('[data-test=ops-like]').attributes('aria-pressed')).toBe('true')
    await bubble.get('[data-test=ops-adopt]').trigger('click')
    await flushPromises()
    expect(bubble.get('[data-test=ops-feedback-error]').text()).toContain('暂时不可用')
    fail = false
    await bubble.get('[data-test=ops-adopt]').trigger('click')
    await flushPromises()
    expect(bubble.find('[data-test=ops-feedback-error]').exists()).toBe(false)
    expect(bubble.get('[data-test=ops-adopt]').attributes('aria-pressed')).toBe('true')
  })

  it('降级必须可见（R7），工具行只显示名称与状态摘要', async () => {
    const { wrapper } = await mountRail({
      [CHAT]: () =>
        sse(
          `event: tool_call\ndata: ${JSON.stringify({ tool_name: 'get_inventory_alerts', call_id: 't-1', status: 'STARTED', summary: '正在处理', arguments: { secret: 'SECRET-ARG' } })}\n\n` +
            `event: turn_complete\ndata: ${JSON.stringify(
              answer('c-1', '库存数据部分不可用。', {
                degraded: true,
                degraded_reason: '库存快照暂不可用',
                tool_calls: [
                  {
                    tool_name: 'get_inventory_alerts',
                    call_id: 't-1',
                    status: 'DEGRADED',
                    summary: '暂时不可用',
                  },
                ],
              }),
            )}\n\n`,
        ),
      [LIST]: () => json(page([summary('c-1', '库存')])),
    })
    await ask(wrapper, '库存')
    expect(wrapper.text()).toContain('本次回答已降级：库存快照暂不可用')
    const rows = wrapper.findAll('[data-test=ops-tool-row]')
    expect(rows).toHaveLength(1)
    expect(rows[0]!.text()).toContain('get_inventory_alerts')
    expect(rows[0]!.text()).toContain('暂时不可用')
    expect(wrapper.text()).not.toContain('SECRET-ARG')
  })

  it('来源级降级原因也逐条展示（R7）', async () => {
    const { wrapper } = await mountRail({
      [CHAT]: () =>
        turnStream('c-1', '规则部分没查到。', {
          analysis_sources: [
            { source: 'DATABASE', degraded: false, degraded_reason: null },
            { source: 'KNOWLEDGE_BASE', degraded: true, degraded_reason: '知识库暂不可用' },
          ],
        }),
      [LIST]: () => json(page([summary('c-1', '规则')])),
    })
    await ask(wrapper, '规则')

    expect(wrapper.text()).toContain('来源 KNOWLEDGE_BASE 降级：知识库暂不可用')
  })

  it('图表可视化 enabled 时挂载图表面板', async () => {
    const { wrapper } = await mountRail({
      [CHAT]: () =>
        turnStream('c-1', '过去 3 天的成交总额如上。', {
          visualization: {
            enabled: true,
            type: 'LINE',
            allowed_types: ['LINE'],
            title: '成交总额趋势',
            dimension_key: 'date',
            metric_key: 'gross_gmv',
            unit: '元',
            data: [{ date: '2026-09-20', gross_gmv: '100' }],
          },
        }),
      [LIST]: () => json(page([summary('c-1', '你好')])),
    })
    await ask(wrapper, '帮我看看成交总额趋势')

    expect(wrapper.find('[data-test=ops-chart]').exists()).toBe(true)
  })

  it('图表可视化缺省（普通问答）时不挂载图表面板', async () => {
    const { wrapper } = await mountRail({
      [CHAT]: () => turnStream('c-1', '你好，我可以帮你查询经营数据。'),
      [LIST]: () => json(page([summary('c-1', '你好')])),
    })
    await ask(wrapper, '你好')

    expect(wrapper.find('[data-test=ops-chart]').exists()).toBe(false)
  })

  // ---------------- 历史面板：新建、浏览、打开、删除 ----------------

  it('如实说明草稿审批要求；历史面板默认收起，点「历史」展开，显示空目录', async () => {
    const { wrapper } = await mountRail({ [LIST]: () => json(page([])) })
    expect(wrapper.text()).toContain('草稿要到审批页核对后批准')

    const toggle = wrapper.get('[data-test=rail-history-toggle]')
    expect(toggle.attributes('aria-pressed')).toBe('false')
    expect(toggle.attributes('aria-controls')).toBe('assistant-rail-history')
    expect(isShown(wrapper, '#assistant-rail-history')).toBe(false)

    await showHistory(wrapper)
    expect(toggle.attributes('aria-pressed')).toBe('true')
    expect(isShown(wrapper, '#assistant-rail-history')).toBe(true)
    expect(wrapper.get('#assistant-rail-history').text()).toContain('还没有历史对话。')
  })

  it('浏览：历史面板按服务端顺序列出当前商家的对话', async () => {
    const { wrapper } = await mountRail({
      [LIST]: () => json(page([summary('c-2', '第二段'), summary('c-1', '第一段')])),
    })
    await showHistory(wrapper)

    const titles = wrapper.findAll('[data-test=ops-conversation-open]').map((item) => item.text())
    expect(titles[0]).toContain('第二段')
    expect(titles[1]).toContain('第一段')
  })

  it('打开对话后回到对话面板并标记当前项', async () => {
    const { wrapper } = await mountRail({
      [LIST]: () => json(page([summary('c-1', '旧对话')])),
      'GET /api/v2/merchant/conversations/c-1': () =>
        json({
          conversation: summary('c-1', '旧对话'),
          messages: page([
            {
              id: 'm-1',
              role: 'user',
              content: '旧提问',
              created_at: '2026-09-24T00:00:01Z',
              answer: null,
              feedback: null,
            },
          ]),
        }),
    })
    await showHistory(wrapper)
    await wrapper.get('[data-test=ops-conversation-open]').trigger('click')
    await flushPromises()

    expect(isShown(wrapper, '#assistant-rail-history')).toBe(false)
    expect(wrapper.get('.ops-view__log').text()).toContain('旧提问')
    expect(wrapper.get('[data-test=ops-conversation-open]').attributes('aria-current')).toBe('true')
  })

  it('新建：头部「新建对话」清空当前对话，下一条消息不带 conversation_id', async () => {
    const bodies: unknown[] = []
    const { wrapper } = await mountRail({
      [CHAT]: (body) => {
        bodies.push(body)
        return turnStream(bodies.length === 1 ? 'c-1' : 'c-2', `回答${bodies.length}`)
      },
      [LIST]: () => json(page([summary('c-1', '第一段')])),
    })
    await ask(wrapper, '第一问')
    expect(wrapper.text()).toContain('回答1')

    await wrapper.get('[data-test=rail-new]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.ops-view__log').text()).not.toContain('回答1')

    await ask(wrapper, '第二问')
    expect((bodies[1] as Record<string, unknown>).conversation_id ?? null).toBeNull()
  })

  it('删除后列表移除；当前对话被删则回到新建态，下一条消息开启新对话', async () => {
    let deleted = false
    const { wrapper } = await mountRail({
      [CHAT]: () => turnStream(deleted ? 'c-9' : 'c-1', deleted ? '新回答' : '当前回答'),
      [LIST]: () => json(page(deleted ? [] : [summary('c-1', '库存怎么样')])),
      'DELETE /api/v2/merchant/conversations/c-1': () => {
        deleted = true
        return json(null, 204)
      },
    })
    await ask(wrapper, '库存怎么样')
    expect(wrapper.text()).toContain('当前回答')
    await showHistory(wrapper)
    const item = wrapper.get('[data-test=ops-conversation-item]')
    expect(item.get('[data-test=ops-conversation-open]').attributes('aria-current')).toBe('true')

    await item.get('[data-test=ops-conversation-delete]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=ops-conversation-item]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('当前回答')
    expect(useOpsChatStore().conversationId).toBeNull()
  })

  it('删除失败时显示错误，列表保留', async () => {
    const { wrapper } = await mountRail({
      [LIST]: () => json(page([summary('c-1', '留着')])),
      'DELETE /api/v2/merchant/conversations/c-1': () =>
        json(
          {
            code: 'SERVICE_UNAVAILABLE',
            message: 'x',
            request_id: 'r',
            details: [],
            retryable: true,
          },
          503,
        ),
    })
    await showHistory(wrapper)
    await wrapper.get('[data-test=ops-conversation-delete]').trigger('click')
    await flushPromises()
    expect(wrapper.get('#assistant-rail [role=alert]').text()).toContain('删除失败')
    expect(wrapper.findAll('[data-test=ops-conversation-item]')).toHaveLength(1)
  })

  // ---------------- 身份与商家隔离 ----------------

  it('冷启动（auth store 尚未 restore）时外壳恢复商家，助手栏随后用新会话拉目录', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    const backend = routeFetch({ [SESSIONS]: () => session(), [LIST]: () => json(page([])) })
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/?assistant=open')
    await router.isReady()
    const wrapper = await mountApp(router, pinia)
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-switcher"]').text()).toContain('Borough商家100')
    expect(backend.seen).toContain(SESSIONS)
    expect(backend.seen).toContain(LIST)
    // 商家恢复完成之前不抢着建会话，不会重复拉演示商家或重复建会话。
    expect(backend.count(SESSIONS)).toBe(1)
  })

  it('切换商家后丢弃当前会话，改用新会话重新拉取会话目录', async () => {
    let listCalls = 0
    const { wrapper } = await mountRail({
      [LIST]: () => {
        listCalls += 1
        return json(page(listCalls === 1 ? [summary('c-1', '库存怎么样')] : []))
      },
      [SESSIONS]: () => session('1', 'Borough商家101'),
    })
    await showHistory(wrapper)
    expect(wrapper.text()).toContain('库存怎么样')
    await wrapper.get('[data-test=ops-input]').setValue('只属于商家100的经营问题')

    await wrapper.get('[data-testid="merchant-switcher"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-switcher"]').text()).toContain('Borough商家101')
    expect(listCalls).toBe(2)
    expect(wrapper.text()).not.toContain('库存怎么样')
    expect((wrapper.get('[data-test=ops-input]').element as HTMLTextAreaElement).value).toBe('')
  })

  // ---------------- 双语 ----------------

  it('英文模式下界面文案为英文', async () => {
    i18n.global.locale.value = 'en-US'
    const { wrapper } = await mountRail({ [LIST]: () => json(page([])) })
    const rail = wrapper.get('#assistant-rail')
    expect(rail.text()).toContain('Operations assistant')
    expect(wrapper.text()).not.toContain('运营助手')
  })
})
