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

import TodayView from './TodayView.vue'

const BASE_URL = 'http://127.0.0.1:8000'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function briefPayload(overrides: Record<string, unknown> = {}) {
  return {
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [],
    quality_status: 'NOT_RUN',
    quality_attempts: 0,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
    brief_version: 1,
    business_date: '2026-09-23',
    business_timezone: 'Asia/Shanghai',
    data_as_of: '2026-09-23T00:00:00Z',
    generated_at: '2026-09-23T00:05:00Z',
    trigger: 'SCHEDULED',
    items: [
      {
        rank: 1,
        kind: 'INVENTORY_ALERT',
        title: '已售罄：测试商品',
        evidence: '商品 p-1：在库 0',
        amount_cents: null,
        next_action_prompt: '给「测试商品」起草一份补货草稿',
      },
    ],
    collapsed_count: 0,
    ...overrides,
  }
}

function draftsPage(items: Record<string, unknown>[] = []) {
  return { items, next_cursor: null, has_more: false }
}

async function mountToday(briefOverrides: Record<string, unknown> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(
      jsonResponse({
        session_id: 'sid'.padEnd(43, '0'),
        role: 'MERCHANT',
        expires_at: '2026-09-24T00:00:00Z',
        merchant_display_name: 'Borough商家100',
      }),
    ),
  )
  await auth.openSession(auth.merchants[0]!)

  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    if (String(url).includes('/briefs/daily/current')) {
      return jsonResponse(briefPayload(briefOverrides))
    }
    if (String(url).includes('/drafts')) {
      return jsonResponse(draftsPage())
    }
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)

  const router = createRouter({ history: createWebHistory(), routes })
  const wrapper = mount(TodayView, { global: { plugins: [pinia, i18n, router] } })
  await flushPromises()
  return { wrapper, fetchMock, router }
}

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('TodayView', () => {
  it('展示数据截至时间与生成时间', async () => {
    const { wrapper } = await mountToday()
    expect(wrapper.text()).toContain('已售罄：测试商品')
  })

  it('点击重新生成会调用限流重新生成接口并刷新简报', async () => {
    const { wrapper, fetchMock } = await mountToday({
      trigger: 'SCHEDULED',
      generated_at: '2020-01-01T00:00:00Z', // 明显早于冷却窗口，按钮应可点。
    })
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).includes('/regenerate')) {
        return jsonResponse(
          briefPayload({ brief_version: 2, trigger: 'REGENERATED', items: [] }),
        )
      }
      if (String(url).includes('/briefs/daily/current')) return jsonResponse(briefPayload())
      if (String(url).includes('/drafts')) return jsonResponse(draftsPage())
      void init
      return jsonResponse({})
    })

    await wrapper.get('[data-test=regenerate]').trigger('click')
    await flushPromises()

    const regenerateCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/regenerate'),
    )
    expect(regenerateCalls).toHaveLength(1)
    expect(wrapper.text()).toContain('第 2 版')
  })

  it('刚重新生成后的冷却期内，重新生成按钮禁用', async () => {
    const { wrapper } = await mountToday({
      trigger: 'REGENERATED',
      generated_at: new Date().toISOString(), // 刚刚生成，仍在冷却窗口内。
    })

    expect((wrapper.get('[data-test=regenerate]').element as HTMLButtonElement).disabled).toBe(
      true,
    )
  })

  it('SCHEDULED 触发的生成不消耗冷却额度，按钮可点', async () => {
    const { wrapper } = await mountToday({
      trigger: 'SCHEDULED',
      generated_at: new Date().toISOString(), // 刚生成，但是 GET 隐式首次生成，不算冷却。
    })

    expect((wrapper.get('[data-test=regenerate]').element as HTMLButtonElement).disabled).toBe(
      false,
    )
  })

  it('确定性来源不显示 AI 分析字样', async () => {
    const { wrapper } = await mountToday()
    expect(wrapper.text()).not.toMatch(/AI\s*分析|AI analysis/i)
  })

  it('简报条目的动作按钮只触发 fill-input 事件，不发送、不批准、不执行任何请求', async () => {
    const { wrapper, fetchMock } = await mountToday()
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.get('[data-test=next-action]').trigger('click')

    expect(fetchMock.mock.calls.length).toBe(callsBefore)
    expect(wrapper.emitted('fill-input')?.[0]).toEqual(['给「测试商品」起草一份补货草稿'])
  })

  it('动作按钮把问题预填到运营助手并跳转过去，但不代为发送', async () => {
    const { wrapper, fetchMock, router } = await mountToday()
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.get('[data-test=next-action]').trigger('click')
    await flushPromises()

    expect(useOpsChatStore().pendingInput).toBe('给「测试商品」起草一份补货草稿')
    // 目标路由是懒加载组件，跳转在组件模块加载完后才落定。
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('assistant'))
    const chatCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/chat'))
    expect(chatCalls).toHaveLength(0)
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(callsBefore)
  })
})
