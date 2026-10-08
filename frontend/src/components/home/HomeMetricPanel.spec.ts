/**
 * 首页主指标面板（W Task 8，契约 §8.12.4）。
 *
 * 数字、比例、贡献只来自 overview 响应：测试特意构造「与序列求和不一致」的载荷，
 * 若组件自己重算就会露馅（R4）。趋势图懒加载、空闲且进入视口后才挂载（首屏门禁）。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { setLocaleProvider } from '@/api/credentials'
import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'
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
import { errorResponse, jsonResponse, overviewPayload } from '@/testing/homePayloads'

import HomeMetricPanel from './HomeMetricPanel.vue'

vi.mock('echarts/core', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() })),
  use: vi.fn(),
}))

async function mountPanel(handler: RouteHandler, idle: typeof idleNow = idleNow) {
  const pinia = pinnedSessionPinia()
  const fetchMock = vi.fn(routeFetch([['/api/v2/merchant/metrics/overview', handler]]))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('requestIdleCallback', idle)
  const wrapper = mount(HomeMetricPanel, { global: { plugins: [pinia, i18n] } })
  await flushPromises()
  return { wrapper, fetchMock }
}

async function revealChart(): Promise<void> {
  ManualIntersectionObserver.revealAll()
  await flushPromises()
  await vi.dynamicImportSettled()
  await flushPromises()
}

beforeEach(() => {
  // 与 main.ts 相同：请求语言取自当前 Pinia 的 locale store。
  setLocaleProvider(() => useLocaleStore().locale)
  vi.stubEnv('VITE_API_BASE_URL', TEST_BASE_URL)
  vi.stubGlobal('IntersectionObserver', ManualIntersectionObserver)
  ManualIntersectionObserver.reset()
})

afterEach(() => {
  setLocaleProvider(undefined)
  i18n.global.locale.value = 'zh-CN'
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('HomeMetricPanel：主指标', () => {
  it('空闲前不请求 overview', async () => {
    const { fetchMock } = await mountPanel(json(overviewPayload()), idleNever)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('大数字、变化比例与基期全部取自响应字段，组件不据序列重算', async () => {
    // current_cents 与序列之和（1,234,500）故意不一致；比例也与两数之比不一致。
    const payload = overviewPayload()
    payload.headline = {
      ...payload.headline,
      current_cents: 999900,
      baseline_cents: 500000,
      change_ratio_bp: 1234,
    }
    const { wrapper } = await mountPanel(json(payload))

    const value = wrapper.get('[data-test=metric-value]').text()
    expect(value).toContain('9,999.00')
    expect(value).not.toContain('12,345')
    expect(wrapper.get('[data-test=metric-change]').text()).toContain('12.3%')
    expect(wrapper.get('[data-test=metric-baseline]').text()).toContain('5,000.00')
    expect(wrapper.get('[data-test=metric-period]').text()).toContain('本周前 3 天')
  })

  it('变化比例为 null 时不显示比例，说明基期无可比数据', async () => {
    const payload = overviewPayload()
    payload.headline = {
      ...payload.headline,
      baseline_cents: null,
      change_ratio_bp: null,
      baseline_series: [],
    }
    const { wrapper } = await mountPanel(json(payload))
    expect(wrapper.find('[data-test=metric-change]').exists()).toBe(false)
    expect(wrapper.get('[data-test=metric-baseline]').text()).toContain('无可比数据')
  })

  it('注明数据来源与截至时间（R7），不出现 AI 分析字样', async () => {
    const { wrapper } = await mountPanel(json(overviewPayload()))
    const meta = wrapper.get('[data-test=metric-meta]').text()
    expect(meta).toContain('经营数据库')
    expect(meta).toContain('数据截至')
    expect(meta).toContain('实时与日汇总')
    expect(wrapper.text()).not.toMatch(/AI\s*分析|AI analysis/i)
  })

  it('如实说明订单量口径：含历史导入订单，与最近订单、订单页的条数可能不同', async () => {
    const { wrapper } = await mountPanel(json(overviewPayload()))
    expect(wrapper.get('[data-test=metric-order-scope]').text()).toContain('历史导入订单')
  })
})

describe('HomeMetricPanel：趋势图', () => {
  // 首次动态 import 要现场转换图表模块；负载高时会吃掉用例自身 5 秒预算而偶发超时
  //（2026-10-02 实测 5.14 s）。在钩子里预热，用例只测「空闲 + 进入视口才挂载」的门控本身。
  // 钩子自己也给足时间：全量并行时这次转换实测会超过默认的 10 秒钩子超时（2026-10-04 两次），
  // 钩子一超时，后面的用例就在模块还没转换完的情况下开跑并连带超时。只放宽预热，不放宽用例。
  beforeAll(async () => {
    await import('./HomeTrendChart.vue')
  }, 60_000)

  it('空闲后且进入视口才挂载懒加载的趋势图', async () => {
    const { wrapper } = await mountPanel(json(overviewPayload()))
    expect(wrapper.find('[data-test=home-trend-chart]').exists()).toBe(false)

    await revealChart()

    expect(wrapper.find('[data-test=home-trend-chart]').exists()).toBe(true)
  })

  it('降级时显示原因，不画趋势图', async () => {
    const { wrapper } = await mountPanel(
      json(overviewPayload({ degraded: true, degraded_reason: '退货率暂时无法读取' })),
    )
    await revealChart()

    const notice = wrapper.get('[data-test=metric-degraded]')
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('退货率暂时无法读取')
    expect(wrapper.find('[data-test=home-trend-chart]').exists()).toBe(false)
  })
})

describe('HomeMetricPanel：变化来自哪里', () => {
  it('列出前 5 个类目的贡献，另起一行说明其余 N 个类目', async () => {
    const { wrapper } = await mountPanel(json(overviewPayload()))
    const rows = wrapper.findAll('[data-test=attribution-row]')
    expect(rows).toHaveLength(5)
    expect(rows[0]!.text()).toContain('男装')
    expect(rows[0]!.text()).toContain('712.00')
    const remaining = wrapper.get('[data-test=attribution-remaining]').text()
    expect(remaining).toContain('其余 3 个类目')
    expect(remaining).toContain('36.00')
  })

  it('即使响应多于 5 项也只列前 5 项', async () => {
    const payload = overviewPayload()
    payload.attribution = {
      ...payload.attribution,
      segments: [
        ...payload.attribution.segments,
        {
          name: '第六类',
          current_cents: 1,
          baseline_cents: 0,
          contribution_cents: 1,
          share_bp: null,
        },
      ],
    }
    const { wrapper } = await mountPanel(json(payload))
    expect(wrapper.findAll('[data-test=attribution-row]')).toHaveLength(5)
    expect(wrapper.text()).not.toContain('第六类')
  })

  it('SHARE 模式显示响应里的占比（万分比），不自行计算', async () => {
    const payload = overviewPayload()
    payload.attribution = {
      ...payload.attribution,
      mode: 'SHARE',
      segments: payload.attribution.segments.map((segment, index) => ({
        ...segment,
        share_bp: index === 0 ? 7777 : 100,
      })),
    }
    const { wrapper } = await mountPanel(json(payload))
    expect(wrapper.findAll('[data-test=attribution-row]')[0]!.text()).toContain('77.8%')
  })

  it('STOPPED 时显示停止原因，不列类目', async () => {
    const payload = overviewPayload()
    payload.attribution = {
      dimension: 'category',
      mode: 'STOPPED',
      segments: [],
      remaining_count: 0,
      remaining_contribution_cents: 0,
      stopped_reason: '上周没有可比数据，暂不归因。',
    }
    const { wrapper } = await mountPanel(json(payload))
    expect(wrapper.get('[data-test=attribution-stopped]').text()).toContain(
      '上周没有可比数据，暂不归因。',
    )
    expect(wrapper.findAll('[data-test=attribution-row]')).toHaveLength(0)
    expect(wrapper.find('[data-test=attribution-remaining]').exists()).toBe(false)
  })

  it('结论句点名贡献最大的类目，「问助手原因」只预填不发送', async () => {
    const { wrapper, fetchMock } = await mountPanel(json(overviewPayload()))
    expect(wrapper.get('[data-test=attribution-why]').text()).toContain('男装')
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.get('[data-test=attribution-ask]').trigger('click')

    expect(useOpsChatStore().pendingInput).not.toBe('')
    expect(useRailStore().open).toBe(true)
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
  })
})

describe('HomeMetricPanel：辅助指标', () => {
  it('三项依次为订单量、退款金额、退货率，按单位格式化', async () => {
    const { wrapper } = await mountPanel(json(overviewPayload()))
    const minis = wrapper.findAll('[data-test=secondary-metric]')
    expect(minis).toHaveLength(3)
    expect(minis[0]!.text()).toContain('订单量')
    expect(minis[0]!.text()).toContain('86')
    expect(minis[1]!.text()).toContain('退款金额')
    expect(minis[1]!.text()).toContain('459.00')
    expect(minis[2]!.text()).toContain('退货率')
    expect(minis[2]!.text()).toContain('12.4%')
  })

  it('值为 null 时显示「暂无数据」而不是 0', async () => {
    const payload = overviewPayload({ degraded: true, degraded_reason: '退款金额暂时无法读取' })
    payload.secondary = [
      { metric_code: 'order_count', unit: 'COUNT', current_value: 86, baseline_value: 91 },
      { metric_code: 'refund_amount', unit: 'CENTS', current_value: null, baseline_value: null },
      { metric_code: 'return_rate', unit: 'RATIO_BP', current_value: 0, baseline_value: null },
    ]
    const { wrapper } = await mountPanel(json(payload))
    const minis = wrapper.findAll('[data-test=secondary-metric]')
    expect(minis[1]!.get('[data-test=secondary-current]').text()).toBe('暂无数据')
    expect(minis[1]!.text()).not.toMatch(/¥\s*0/)
    // 真实的 0 照常显示为 0%，基期为 null 同样写「暂无数据」。
    expect(minis[2]!.get('[data-test=secondary-current]').text()).toBe('0%')
    expect(minis[2]!.get('[data-test=secondary-baseline]').text()).toContain('暂无数据')
  })

  it('点击任一项只预填问题并打开助手栏，不发请求', async () => {
    const { wrapper, fetchMock } = await mountPanel(json(overviewPayload()))
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.findAll('[data-test=secondary-metric]')[1]!.trigger('click')

    expect(useOpsChatStore().pendingInput).toContain('退款金额')
    expect(useRailStore().open).toBe(true)
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
  })
})

describe('HomeMetricPanel：语言', () => {
  it('切换展示语言后重新取数，周期说明等后端文案随之换成新语言（R1）', async () => {
    const { fetchMock } = await mountPanel(json(overviewPayload()))
    expect(fetchMock).toHaveBeenCalledTimes(1)

    useLocaleStore().setLocale('en-US')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})

/** 按调用顺序挂起的响应：测试决定每个请求何时、以什么内容返回。 */
function deferredResponses() {
  const pending: Array<{ locale: string | null; resolve: (response: Response) => void }> = []
  const handler: RouteHandler = (_url, init) =>
    new Promise<Response>((resolve) => {
      const headers = (init?.headers ?? {}) as Record<string, string>
      pending.push({ locale: headers['Accept-Language'] ?? null, resolve })
    })
  return { pending, handler }
}

function labelled(label: string) {
  const payload = overviewPayload()
  payload.current_period = { ...payload.current_period, label }
  return payload
}

describe('HomeMetricPanel：请求竞态与重新取数', () => {
  it('旧请求晚于新请求返回时被丢弃：最终显示新请求的结果', async () => {
    const { pending, handler } = deferredResponses()
    const { wrapper } = await mountPanel(handler)
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(pending).toHaveLength(2)

    pending[1]!.resolve(jsonResponse(labelled('First 3 days of this week')))
    await flushPromises()
    pending[0]!.resolve(jsonResponse(labelled('本周前 3 天')))
    await flushPromises()

    expect(wrapper.get('[data-test=metric-period]').text()).toContain('First 3 days of this week')
  })

  it('加载途中切换语言不会被跳过：新语言的请求照发，最终是新语言的结果', async () => {
    const { pending, handler } = deferredResponses()
    const { wrapper } = await mountPanel(handler)
    expect(pending).toHaveLength(1)

    useLocaleStore().setLocale('en-US')
    await flushPromises()

    expect(pending).toHaveLength(2)
    expect(pending[1]!.locale).toBe('en-US')
    pending[0]!.resolve(jsonResponse(labelled('本周前 3 天')))
    await flushPromises()
    pending[1]!.resolve(jsonResponse(labelled('First 3 days of this week')))
    await flushPromises()

    expect(wrapper.get('[data-test=metric-period]').text()).toContain('First 3 days of this week')
  })

  it('重新取数时保留上一份数据与已挂载的趋势图，只显示「正在更新」', async () => {
    const { pending, handler } = deferredResponses()
    const { wrapper } = await mountPanel(handler)
    pending[0]!.resolve(jsonResponse(overviewPayload()))
    await flushPromises()
    await revealChart()
    const chartElement = wrapper.find('[data-test=home-trend-chart]').element
    expect(chartElement).toBeDefined()

    useLocaleStore().setLocale('en-US')
    await flushPromises()

    expect(wrapper.get('[data-test=metric-value]').text()).toContain('12,345.00')
    expect(wrapper.get('[data-test=metric-refreshing]').attributes('role')).toBe('status')
    expect(wrapper.get('[data-test=home-metric]').attributes('aria-busy')).toBe('true')
    // 同一个 DOM 节点：趋势图没有被卸载重建（比较布尔值，失败时不去序列化整棵组件树）。
    expect(wrapper.find('[data-test=home-trend-chart]').element === chartElement).toBe(true)

    pending[1]!.resolve(jsonResponse(overviewPayload()))
    await flushPromises()
    expect(wrapper.find('[data-test=metric-refreshing]').exists()).toBe(false)
  })

  it('重新取数失败时保留上一份数据，另给出失败说明与重试', async () => {
    const { pending, handler } = deferredResponses()
    const { wrapper } = await mountPanel(handler)
    pending[0]!.resolve(jsonResponse(overviewPayload()))
    await flushPromises()

    useLocaleStore().setLocale('en-US')
    await flushPromises()
    pending[1]!.resolve(errorResponse(503))
    await flushPromises()

    expect(wrapper.get('[data-test=metric-value]').text()).toContain('12,345.00')
    expect(wrapper.get('[role=alert]').text()).toContain('Store metrics are unavailable right now.')
    expect(wrapper.find('[data-test=metric-retry]').exists()).toBe(true)
  })
})

describe('HomeMetricPanel：无障碍', () => {
  it('加载中、失败、就绪三种状态下区块都有名称', async () => {
    const loading = await mountPanel(json(overviewPayload()), idleNever)
    expect(loading.wrapper.get('[data-test=home-metric]').attributes('aria-label')).toBe('净成交额')
    loading.wrapper.unmount()

    const failed = await mountPanel(failing())
    expect(failed.wrapper.get('[data-test=home-metric]').attributes('aria-label')).toBe('净成交额')
    failed.wrapper.unmount()

    const ready = await mountPanel(json(overviewPayload()))
    expect(ready.wrapper.get('[data-test=home-metric]').attributes('aria-label')).toBe('净成交额')
  })
})

describe('HomeMetricPanel：取数失败', () => {
  it('overview 不可用时显示该面板不可用并可重试，不显示任何示意数字', async () => {
    let fail = true
    const { wrapper, fetchMock } = await mountPanel((url, init) =>
      fail ? failing()(url, init) : json(overviewPayload())(url, init),
    )
    expect(wrapper.get('[role=alert]').text()).toContain('经营指标暂时无法读取')
    expect(wrapper.find('[data-test=metric-value]').exists()).toBe(false)

    fail = false
    await wrapper.get('[data-test=metric-retry]').trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-test=metric-value]').text()).toContain('12,345.00')
  })
})
