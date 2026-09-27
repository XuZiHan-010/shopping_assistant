import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { routes } from '@/router'
import { useAuthStore } from '@/stores/auth'
import { useOpsChatStore } from '@/stores/opsChat'

import OpsAssistantView from './OpsAssistantView.vue'

const BASE_URL = 'http://127.0.0.1:8000'
const LIST = 'GET /api/v2/merchant/conversations'
const CHAT = 'POST /api/v2/merchant/chat'

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

function routeFetch(routes: Record<string, Handler>) {
  const seen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const key = `${(init?.method ?? 'GET').toUpperCase()} ${new URL(String(input)).pathname}`
      seen.push(key)
      const handler = routes[key]
      if (!handler) throw new Error(`未登记的路由：${key}`)
      return handler(typeof init?.body === 'string' ? JSON.parse(init.body) : undefined)
    }),
  )
  return { count: (key: string) => seen.filter((k) => k === key).length }
}

async function mountOps(routesTable: Record<string, Handler>, before?: () => void) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(
      json(
        {
          session_id: 'sid'.padEnd(43, '0'),
          role: 'MERCHANT',
          expires_at: '2099-01-01T00:00:00Z',
          merchant_display_name: 'Borough商家100',
        },
        201,
      ),
    ),
  )
  await auth.openSession(auth.merchants[0]!)
  before?.()
  const backend = routeFetch(routesTable)
  const router = createRouter({ history: createWebHistory(), routes })
  await router.push({ name: 'assistant' })
  // `MetricChartPanel` 是异步组件（`defineAsyncComponent`）；真正走动态 import()
  // 会在测试环境拆除后才 resolve，报出 "caught after test environment was torn
  // down"（`AssistantView.spec.ts` 已有同样问题与同样的处理方式）。stub 掉，
  // 只验证"是否挂载"，不测组件内部渲染——内部渲染由 `InsightPanels.spec.ts` 覆盖。
  const wrapper = mount(OpsAssistantView, {
    global: {
      plugins: [pinia, i18n, router],
      stubs: { MetricChartPanel: { template: '<section data-test="ops-chart" />' } },
    },
  })
  await flushPromises()
  return { wrapper, backend }
}

async function ask(wrapper: Awaited<ReturnType<typeof mountOps>>['wrapper'], text: string) {
  await wrapper.get('[data-test=ops-input]').setValue(text)
  await wrapper.get('[data-test=ops-form]').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  i18n.global.locale.value = 'zh-CN'
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('OpsAssistantView', () => {
  it('当前回答可采纳、赞踩并填写原因；按 v2 kind 提交且显示回执', async () => {
    const requests: unknown[] = []
    let adopted = false
    const { wrapper } = await mountOps({
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
    const { wrapper } = await mountOps({
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
  it('如实说明草稿审批要求，并给出今日简报、库存告警、知识库入口（两页合并后不再链接回自己）', async () => {
    const { wrapper } = await mountOps({ [LIST]: () => json(page([])) })
    expect(wrapper.text()).toContain('草稿要到审批页核对后批准')
    const hrefs = wrapper.findAll('nav a').map((a) => a.attributes('href'))
    expect(hrefs).toEqual(expect.arrayContaining(['/today', '/inventory', '/knowledge-base']))
    expect(hrefs).not.toContain('/')
    expect(wrapper.text()).toContain('还没有历史对话。')
  })

  it('提供商家切换入口（两页合并后 v1 独有的切换器随之接入，2026-09-27）', async () => {
    const { wrapper } = await mountOps({ [LIST]: () => json(page([])) })

    expect(wrapper.get('[data-testid="merchant-switcher"]').text()).toContain('Borough商家100')
  })

  it('提供语言切换入口（两页合并前 `/` 上唯一能切语言的地方是 v1 头部，2026-09-27 随合并接入）', async () => {
    const { wrapper } = await mountOps({ [LIST]: () => json(page([])) })

    expect(wrapper.find('[data-testid="language-switcher"]').exists()).toBe(true)
  })

  it('冷启动（auth store 尚未 restore）时自己拉商家列表并选中默认商家，不依赖 v1 页面先跑过', async () => {
    // 两页合并前，本页只作为并存页面存在：用户总是先经过 `/`（v1 `AssistantView`）
    // 完成身份 restore 才会手动切过来。合并后 `/` 首次挂载的就是本页，必须自己
    // 负责这一步——这里故意不调用其它测试共用的 `mountOps()`（它会预先手动
    // `loadMerchants`/`openSession`，掩盖了这条依赖），从真正干净的 Pinia 开始。
    const pinia = createPinia()
    setActivePinia(pinia)
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
    const seen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const key = `${(init?.method ?? 'GET').toUpperCase()} ${new URL(String(input)).pathname}`
        seen.push(key)
        if (key === 'POST /api/v2/merchant/sessions') {
          return json(
            {
              session_id: 'sid'.padEnd(43, '0'),
              role: 'MERCHANT',
              expires_at: '2099-01-01T00:00:00Z',
              merchant_display_name: 'Borough商家100',
            },
            201,
          )
        }
        if (key === LIST) return json(page([]))
        throw new Error(`未登记的路由：${key}`)
      }),
    )

    const router = createRouter({ history: createWebHistory(), routes })
    await router.push({ name: 'assistant' })
    const wrapper = mount(OpsAssistantView, {
      global: {
        plugins: [pinia, router, i18n],
        stubs: { MetricChartPanel: { template: '<section data-test="ops-chart" />' } },
      },
    })
    await flushPromises()
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-switcher"]').text()).toContain('Borough商家100')
    expect(seen).toContain('POST /api/v2/merchant/sessions')
    expect(seen).toContain(LIST)
  })

  it('切换商家后丢弃当前会话，改用新会话重新拉取会话目录', async () => {
    let listCalls = 0
    const { wrapper } = await mountOps({
      [LIST]: () => {
        listCalls += 1
        return json(page(listCalls === 1 ? [summary('c-1', '库存怎么样')] : []))
      },
      'POST /api/v2/merchant/sessions': () =>
        json(
          {
            session_id: 'sid'.padEnd(43, '1'),
            role: 'MERCHANT',
            expires_at: '2099-01-01T00:00:00Z',
            merchant_display_name: 'Borough商家101',
          },
          201,
        ),
    })
    expect(wrapper.text()).toContain('库存怎么样')

    await wrapper.get('[data-testid="merchant-switcher"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-switcher"]').text()).toContain('Borough商家101')
    expect(listCalls).toBe(2)
    expect(wrapper.text()).not.toContain('库存怎么样')
  })

  it('删除后列表移除；当前对话被删则回到新建态，下一条消息开启新对话', async () => {
    let deleted = false
    const { wrapper } = await mountOps({
      [CHAT]: () => turnStream(deleted ? 'c-9' : 'c-1', deleted ? '新回答' : '当前回答'),
      [LIST]: () => json(page(deleted ? [] : [summary('c-1', '库存怎么样')])),
      'DELETE /api/v2/merchant/conversations/c-1': () => {
        deleted = true
        return json(null, 204)
      },
    })
    await ask(wrapper, '库存怎么样')
    expect(wrapper.text()).toContain('当前回答')
    const item = wrapper.get('[data-test=ops-conversation-item]')
    expect(item.get('[data-test=ops-conversation-open]').attributes('aria-current')).toBe('true')

    await item.get('[data-test=ops-conversation-delete]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=ops-conversation-item]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('当前回答')
    expect(useOpsChatStore().conversationId).toBeNull()
  })

  it('降级必须可见（R7），工具行只显示名称与状态摘要', async () => {
    const { wrapper } = await mountOps({
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

  it('简报预填的问题只填入输入框，不自动发送', async () => {
    const { wrapper, backend } = await mountOps({ [LIST]: () => json(page([])) }, () => {
      useOpsChatStore().prefill('给「测试商品」起草一份补货草稿')
    })
    const input = wrapper.get('[data-test=ops-input]').element as HTMLTextAreaElement
    expect(input.value).toBe('给「测试商品」起草一份补货草稿')
    expect(backend.count(CHAT)).toBe(0)
  })

  it('猜你想问点击后填入输入框，不代为发送', async () => {
    const { wrapper, backend } = await mountOps({
      [CHAT]: () => turnStream('c-1', '好的', { suggestions: ['哪些商品快卖完了？'] }),
      [LIST]: () => json(page([summary('c-1', '你好')])),
    })
    await ask(wrapper, '你好')
    await wrapper.get('[data-test=ops-suggestion]').trigger('click')
    const input = wrapper.get('[data-test=ops-input]').element as HTMLTextAreaElement
    expect(input.value).toBe('哪些商品快卖完了？')
    expect(backend.count(CHAT)).toBe(1)
  })

  it('图表可视化 enabled 时挂载图表面板', async () => {
    const { wrapper } = await mountOps({
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
    const { wrapper } = await mountOps({
      [CHAT]: () => turnStream('c-1', '你好，我可以帮你查询经营数据。'),
      [LIST]: () => json(page([summary('c-1', '你好')])),
    })
    await ask(wrapper, '你好')

    expect(wrapper.find('[data-test=ops-chart]').exists()).toBe(false)
  })

  it('删除失败时显示错误，列表保留', async () => {
    const { wrapper } = await mountOps({
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
    await wrapper.get('[data-test=ops-conversation-delete]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role=alert]').text()).toContain('删除失败')
    expect(wrapper.findAll('[data-test=ops-conversation-item]')).toHaveLength(1)
  })

  it('输入法选词时按回车不发送；普通回车发送', async () => {
    const { wrapper, backend } = await mountOps({
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

  it('英文模式下界面文案为英文', async () => {
    i18n.global.locale.value = 'en-US'
    const { wrapper } = await mountOps({ [LIST]: () => json(page([])) })
    expect(wrapper.text()).toContain('Operations assistant')
    expect(wrapper.text()).not.toContain('运营助手')
  })
})
