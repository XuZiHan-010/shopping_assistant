/**
 * 首页（W Task 8）：问候、今日简报卡、主指标面板、需要你处理、最近订单。
 *
 * 简报卡的断言从已删除的 `TodayView.spec.ts` 迁来（逐条映射见 W Task 8 报告），
 * 另补 R7「不写成 AI 分析」、逐条渲染、降级说明、「去审批（N）」与分源失败隔离。
 * 主指标、需要处理事项与最近订单的细节断言在 `components/home/*.spec.ts`。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

import { i18n } from '@/i18n'
import { routes } from '@/router'
import { useOpsChatStore } from '@/stores/opsChat'
import { useRailStore } from '@/stores/rail'
import {
  failing,
  idleNever,
  idleNow,
  json,
  ManualIntersectionObserver,
  pinnedSessionPinia,
  routeFetch,
  TEST_BASE_URL,
  type RouteHandler,
} from '@/testing/homeHarness'
import {
  briefPayload,
  draftSummary,
  jsonResponse,
  overviewPayload,
  page,
} from '@/testing/homePayloads'

import HomeView from './HomeView.vue'

type Overrides = Partial<
  Record<
    'brief' | 'drafts' | 'overview' | 'orders' | 'alerts' | 'afterSales' | 'signals',
    RouteHandler
  >
>

function homeRoutes(
  overrides: Overrides = {},
  regenerate?: RouteHandler,
): Array<[string, RouteHandler]> {
  return [
    ...(regenerate
      ? ([['/api/v2/merchant/briefs/daily/current/regenerate', regenerate]] as Array<
          [string, RouteHandler]
        >)
      : []),
    ['/api/v2/merchant/briefs/daily/current', overrides.brief ?? json(briefPayload())],
    ['/api/v2/merchant/drafts', overrides.drafts ?? json(page([]))],
    ['/api/v2/merchant/metrics/overview', overrides.overview ?? json(overviewPayload())],
    ['/api/v2/merchant/orders', overrides.orders ?? json(page([]))],
    ['/api/v2/merchant/inventory/alerts', overrides.alerts ?? json(page([]))],
    ['/api/v2/merchant/after-sales', overrides.afterSales ?? json(page([]))],
    ['/api/v2/merchant/customer-signals', overrides.signals ?? json(page([]))],
  ]
}

async function mountHome(
  options: {
    overrides?: Overrides
    brief?: Record<string, unknown>
    idle?: typeof idleNow
  } = {},
) {
  const pinia = pinnedSessionPinia()
  const overrides: Overrides = { ...options.overrides }
  if (options.brief) overrides.brief = json(briefPayload(options.brief))
  const fetchMock = vi.fn(routeFetch(homeRoutes(overrides)))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('requestIdleCallback', options.idle ?? idleNow)

  const router = createRouter({ history: createWebHistory(), routes })
  await router.push('/')
  const wrapper = mount(HomeView, { global: { plugins: [pinia, i18n, router] } })
  await flushPromises()
  return { wrapper, fetchMock, router }
}

function calledPaths(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map(([url]) => new URL(String(url)).pathname)
}

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', TEST_BASE_URL)
  vi.stubGlobal('IntersectionObserver', ManualIntersectionObserver)
  ManualIntersectionObserver.reset()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('HomeView：页面骨架', () => {
  it('问候语带当前商家名，四个区块依次出现', async () => {
    const { wrapper } = await mountHome()
    expect(wrapper.get('h1').text()).toContain('Borough商家100')
    expect(wrapper.find('[data-test=home-brief]').exists()).toBe(true)
    expect(wrapper.find('[data-test=home-metric]').exists()).toBe(true)
    expect(wrapper.find('[data-test=home-attention]').exists()).toBe(true)
    expect(wrapper.find('[data-test=home-recent-orders]').exists()).toBe(true)
  })

  it('首屏不发业务请求：各区块的取数推迟到浏览器空闲之后（首屏门禁）', async () => {
    const { fetchMock } = await mountHome({ idle: idleNever })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('空闲后各区块各自取数', async () => {
    const { fetchMock } = await mountHome()
    const paths = calledPaths(fetchMock)
    expect(paths).toEqual(
      expect.arrayContaining([
        '/api/v2/merchant/briefs/daily/current',
        '/api/v2/merchant/drafts',
        '/api/v2/merchant/metrics/overview',
        '/api/v2/merchant/orders',
        '/api/v2/merchant/inventory/alerts',
        '/api/v2/merchant/after-sales',
        '/api/v2/merchant/customer-signals',
      ]),
    )
  })

  it('整页不出现「AI 分析」字样（R7：简报与指标都是确定性结果）', async () => {
    const { wrapper } = await mountHome()
    expect(wrapper.text()).not.toMatch(/AI\s*分析|AI analysis/i)
  })

  it('某一区块取数失败只影响自己：简报失败时主指标照常显示', async () => {
    const { wrapper } = await mountHome({ overrides: { brief: failing() } })
    expect(wrapper.get('[data-test=home-brief]').find('[role=alert]').exists()).toBe(true)
    expect(wrapper.get('[data-test=home-metric]').text()).toContain('12,345')
  })
})

describe('HomeView：今日简报卡（迁自 TodayView）', () => {
  it('展示数据截至时间与生成时间', async () => {
    const { wrapper } = await mountHome()
    const brief = wrapper.get('[data-test=home-brief]')
    expect(brief.text()).toContain('已售罄：测试商品')
    expect(brief.text()).toContain('数据截至')
    expect(brief.text()).toContain('生成于')
    expect(brief.text()).toContain('第 1 版')
  })

  it('逐条渲染 items 的 title 与 evidence，不拼成一段话', async () => {
    const { wrapper } = await mountHome({
      brief: {
        items: [
          {
            rank: 1,
            kind: 'INVENTORY_ALERT',
            title: '已售罄：甲',
            evidence: '在库 0',
            amount_cents: null,
            next_action_prompt: null,
          },
          {
            rank: 2,
            kind: 'CUSTOMER_SIGNAL',
            title: '内容缺口：乙',
            evidence: '12 位顾客问到尺码',
            amount_cents: null,
            next_action_prompt: '给乙补尺码建议',
          },
        ],
      },
    })
    const items = wrapper.findAll('[data-test=brief-item]')
    expect(items).toHaveLength(2)
    expect(items[0]!.get('[data-test=brief-item-title]').text()).toBe('已售罄：甲')
    expect(items[0]!.get('[data-test=brief-item-evidence]').text()).toBe('在库 0')
    expect(items[1]!.get('[data-test=brief-item-title]').text()).toBe('内容缺口：乙')
    expect(items[1]!.get('[data-test=brief-item-evidence]').text()).toBe('12 位顾客问到尺码')
    // 没有 nextActionPrompt 的条目不渲染「问助手」。
    expect(items[0]!.find('[data-test=next-action]').exists()).toBe(false)
    expect(items[1]!.find('[data-test=next-action]').exists()).toBe(true)
  })

  it('degraded 为真时显示降级说明与原因', async () => {
    const { wrapper } = await mountHome({
      brief: { degraded: true, degraded_reason: '顾客信号暂不可用' },
    })
    const notice = wrapper.get('[data-test=home-brief]').get('[data-test=brief-degraded]')
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('降级')
    expect(notice.text()).toContain('顾客信号暂不可用')
  })

  it('另有折叠条目时显示「另有 N 项」', async () => {
    const { wrapper } = await mountHome({ brief: { collapsed_count: 4 } })
    expect(wrapper.get('[data-test=home-brief]').text()).toContain('另有 4 项')
  })

  it('点击重新生成会调用限流重新生成接口并刷新简报', async () => {
    const pinia = pinnedSessionPinia()
    const fetchMock = vi.fn(
      routeFetch(
        homeRoutes(
          {
            brief: json(
              briefPayload({ trigger: 'SCHEDULED', generated_at: '2020-01-01T00:00:00Z' }),
            ),
          },
          json(briefPayload({ brief_version: 2, trigger: 'REGENERATED', items: [] })),
        ),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('requestIdleCallback', idleNow)
    const router = createRouter({ history: createWebHistory(), routes })
    const wrapper = mount(HomeView, { global: { plugins: [pinia, i18n, router] } })
    await flushPromises()

    await wrapper.get('[data-test=regenerate]').trigger('click')
    await flushPromises()

    const regenerateCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes('/regenerate'),
    )
    expect(regenerateCalls).toHaveLength(1)
    expect(wrapper.text()).toContain('第 2 版')
  })

  it('刚重新生成后的冷却期内，重新生成按钮禁用', async () => {
    const { wrapper } = await mountHome({
      brief: { trigger: 'REGENERATED', generated_at: new Date().toISOString() },
    })
    expect((wrapper.get('[data-test=regenerate]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('SCHEDULED 触发的生成不消耗冷却额度，按钮可点', async () => {
    const { wrapper } = await mountHome({
      brief: { trigger: 'SCHEDULED', generated_at: new Date().toISOString() },
    })
    expect((wrapper.get('[data-test=regenerate]').element as HTMLButtonElement).disabled).toBe(
      false,
    )
  })

  it('后端仍在冷却（429 RATE_LIMITED）时提示稍后再试', async () => {
    const pinia = pinnedSessionPinia()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        routeFetch(
          homeRoutes({}, () =>
            jsonResponse(
              {
                code: 'RATE_LIMITED',
                message: '请求过于频繁',
                request_id: 'r',
                retryable: true,
                details: [],
              },
              429,
            ),
          ),
        ),
      ),
    )
    vi.stubGlobal('requestIdleCallback', idleNow)
    const router = createRouter({ history: createWebHistory(), routes })
    const wrapper = mount(HomeView, { global: { plugins: [pinia, i18n, router] } })
    await flushPromises()

    await wrapper.get('[data-test=regenerate]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test=home-brief]').text()).toContain('刚刚生成过，请稍后再试。')
  })

  it('确定性来源不显示 AI 分析字样', async () => {
    const { wrapper } = await mountHome()
    expect(wrapper.get('[data-test=home-brief]').text()).not.toMatch(/AI\s*分析|AI analysis/i)
  })

  it('简报条目的「问助手」只预填，不发送、不批准、不执行任何请求', async () => {
    const { wrapper, fetchMock } = await mountHome()
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.get('[data-test=next-action]').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.length).toBe(callsBefore)
    expect(useOpsChatStore().pendingInput).toBe('给「测试商品」起草一份补货草稿')
  })

  it('动作按钮把问题预填到运营助手并打开助手栏，留在当前页，不代为发送', async () => {
    const { wrapper, fetchMock, router } = await mountHome()
    const pathBefore = router.currentRoute.value.fullPath
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.get('[data-test=next-action]').trigger('click')
    await flushPromises()

    expect(useOpsChatStore().pendingInput).toBe('给「测试商品」起草一份补货草稿')
    expect(useRailStore().open).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe(pathBefore)
    const chatCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/chat'))
    expect(chatCalls).toHaveLength(0)
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(callsBefore)
  })

  it('待审批数量只按暂存（STAGED）草稿取数', async () => {
    const { fetchMock } = await mountHome()
    const draftsCall = fetchMock.mock.calls
      .map(([url]) => new URL(String(url)))
      .find((url) => url.pathname === '/api/v2/merchant/drafts')
    expect(draftsCall?.searchParams.get('state')).toBe('STAGED')
  })

  it('「去审批（N）」链接到审批页，N 来自草稿 Store', async () => {
    const { wrapper } = await mountHome({
      overrides: {
        drafts: json(page([draftSummary('d-1', '补货：甲'), draftSummary('d-2', '九折券')])),
      },
    })
    const link = wrapper.get('[data-test=go-approve]')
    expect(link.text()).toContain('去审批（2）')
    expect(link.attributes('href')).toBe('/approvals')
  })

  it('草稿不止一页时 N 标为「20+」这类下限，不假装是精确总数', async () => {
    const drafts = Array.from({ length: 20 }, (_, index) =>
      draftSummary(`d-${index}`, `草稿 ${index}`),
    )
    const { wrapper } = await mountHome({ overrides: { drafts: json(page(drafts, true)) } })
    expect(wrapper.get('[data-test=go-approve]').text()).toContain('去审批（20+）')
  })

  it('没有待批准草稿时不显示审批入口，改为「暂无待批准草稿。」', async () => {
    const { wrapper } = await mountHome()
    expect(wrapper.find('[data-test=go-approve]').exists()).toBe(false)
    expect(wrapper.get('[data-test=home-brief]').text()).toContain('暂无待批准草稿。')
  })

  it('草稿列表失败只影响审批入口，简报条目照常显示', async () => {
    const { wrapper } = await mountHome({ overrides: { drafts: failing() } })
    const brief = wrapper.get('[data-test=home-brief]')
    expect(brief.text()).toContain('已售罄：测试商品')
    expect(brief.text()).toContain('待审批数量暂时无法读取')
  })
})
