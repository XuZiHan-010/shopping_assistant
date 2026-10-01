/**
 * 首页「需要你处理」（W Task 8）：聚合库存告警、待商家处理的售后、未忽略的内容缺口信号；
 * 按类别筛选，最多 5 行；每个数据源单独失败只影响自己那一类。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'

import { i18n } from '@/i18n'
import { setLocaleProvider } from '@/api/credentials'
import { useLocaleStore } from '@/stores/locale'
import { deferred } from '@/testing/workspacePayloads'
import { routes } from '@/router'
import { useAfterSalesStore } from '@/stores/afterSales'
import { useInventoryStore } from '@/stores/inventory'
import { useOpsChatStore } from '@/stores/opsChat'
import { useRailStore } from '@/stores/rail'
import { useSignalsStore } from '@/stores/signals'
import {
  failing,
  idleNow,
  json,
  pinnedSessionPinia,
  routeFetch,
  TEST_BASE_URL,
  type RouteHandler,
} from '@/testing/homeHarness'
import {
  afterSaleSummary,
  customerSignal,
  inventoryAlert,
  jsonResponse,
  page,
} from '@/testing/homePayloads'

import HomeAttention from './HomeAttention.vue'

interface Sources {
  alerts?: RouteHandler
  afterSales?: RouteHandler
  signals?: RouteHandler
}

const defaultAlerts = page([
  inventoryAlert('a-1', 'LOW_STOCK', '雪松护手霜', { stock_available: 8, days_of_supply: 4 }),
  inventoryAlert('a-2', 'OUT_OF_STOCK', '轻量通勤夹克'),
])
const defaultAfterSales = page([afterSaleSummary('as-1')])
const defaultSignals = page([
  customerSignal('s-1', 'CONTENT_GAP', '轻量通勤夹克', { count: 12 }),
  customerSignal('s-2', 'CONTENT_GAP', '雪松护手霜', {
    is_ignored: true,
    ignore_reason: '已线下答复',
  }),
  customerSignal('s-3', 'RETURN_REQUESTS', '德比鞋'),
])

async function mountAttention(sources: Sources = {}) {
  const pinia = pinnedSessionPinia()
  const fetchMock = vi.fn(
    routeFetch([
      ['/api/v2/merchant/inventory/alerts', sources.alerts ?? json(defaultAlerts)],
      ['/api/v2/merchant/after-sales', sources.afterSales ?? json(defaultAfterSales)],
      ['/api/v2/merchant/customer-signals', sources.signals ?? json(defaultSignals)],
    ]),
  )
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('requestIdleCallback', idleNow)
  const router = createRouter({ history: createWebHistory(), routes })
  const wrapper = mount(HomeAttention, { global: { plugins: [pinia, i18n, router] } })
  await flushPromises()
  return { wrapper, fetchMock }
}

function rowTitles(wrapper: Awaited<ReturnType<typeof mountAttention>>['wrapper']): string[] {
  return wrapper
    .findAll('[data-test=attention-row] [data-test=attention-title]')
    .map((row) => row.text())
}

beforeEach(() => {
  setLocaleProvider(() => useLocaleStore().locale)
  vi.stubEnv('VITE_API_BASE_URL', TEST_BASE_URL)
})

afterEach(() => {
  setLocaleProvider(undefined)
  i18n.global.locale.value = 'zh-CN'
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('HomeAttention', () => {
  it('语言切换重读售后别名，旧语言慢响应不能覆盖当前事项', async () => {
    const old = deferred<Response>()
    const { wrapper } = await mountAttention({
      afterSales: (_url, init) =>
        new Headers(init?.headers).get('Accept-Language') === 'en-US'
          ? Promise.resolve(
              jsonResponse(page([{ ...afterSaleSummary('as-1'), buyer_alias: 'Buyer TEST' }])),
            )
          : old.promise,
    })
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(wrapper.text()).toContain('Buyer TEST')
    old.resolve(jsonResponse(page([{ ...afterSaleSummary('as-1'), buyer_alias: '旧语言顾客' }])))
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧语言顾客')
    wrapper.unmount()
  })
  it('聚合三类来源：售罄在前，只取待商家处理的售后与未忽略的内容缺口', async () => {
    const { wrapper, fetchMock } = await mountAttention()

    const afterSalesCall = fetchMock.mock.calls
      .map(([url]) => new URL(String(url)))
      .find((url) => url.pathname === '/api/v2/merchant/after-sales')
    expect(afterSalesCall?.searchParams.get('state')).toBe('PENDING_MERCHANT')

    const titles = rowTitles(wrapper)
    expect(titles).toHaveLength(4)
    expect(titles[0]).toContain('轻量通勤夹克')
    expect(
      wrapper.findAll('[data-test=attention-row]').map((row) => row.attributes('data-category')),
    ).toEqual(['stock', 'after', 'stock', 'gap'])
    // 已忽略的缺口与非缺口信号都不出现。
    expect(wrapper.text()).not.toContain('德比鞋')
    expect(wrapper.findAll('[data-category=gap]')).toHaveLength(1)
  })

  it('不写入库存、售后、信号三个共享 Store：售后页的列表、筛选与游标不被首页覆盖', async () => {
    const pinia = pinnedSessionPinia()
    // 模拟售后页已按「全部状态」载入一页并持有游标（首页的 PENDING_MERCHANT 响应晚到也不能覆盖它）。
    const afterSalesStore = useAfterSalesStore(pinia)
    afterSalesStore.items = [
      {
        id: 'as-page',
        orderId: 'o-1',
        type: 'TICKET',
        state: 'REFUNDED',
        refundAmountCents: null,
        buyerAlias: '顾客 A',
        firstResponseDueAt: '2026-09-23T10:00:00Z',
        createdAt: '2026-09-23T02:00:00Z',
      },
    ]
    afterSalesStore.nextCursor = 'cursor-all-states'
    vi.stubGlobal(
      'fetch',
      vi.fn(
        routeFetch([
          ['/api/v2/merchant/inventory/alerts', json(defaultAlerts)],
          ['/api/v2/merchant/after-sales', json(defaultAfterSales)],
          ['/api/v2/merchant/customer-signals', json(defaultSignals)],
        ]),
      ),
    )
    vi.stubGlobal('requestIdleCallback', idleNow)
    const router = createRouter({ history: createWebHistory(), routes })
    const wrapper = mount(HomeAttention, { global: { plugins: [pinia, i18n, router] } })
    await flushPromises()

    expect(wrapper.findAll('[data-test=attention-row]')).toHaveLength(4)
    expect(afterSalesStore.items.map((item) => item.id)).toEqual(['as-page'])
    expect(afterSalesStore.nextCursor).toBe('cursor-all-states')
    expect(afterSalesStore.stateFilter).toBe('')
    expect(useInventoryStore(pinia).items).toEqual([])
    expect(useSignalsStore(pinia).items).toEqual([])
  })

  it('请求参数：售后只取 PENDING_MERCHANT，信号不含已忽略', async () => {
    const { fetchMock } = await mountAttention()
    const urls = fetchMock.mock.calls.map(([url]) => new URL(String(url)))
    const signals = urls.find((url) => url.pathname === '/api/v2/merchant/customer-signals')
    expect(signals?.searchParams.get('include_ignored')).toBe('false')
    const afterSales = urls.find((url) => url.pathname === '/api/v2/merchant/after-sales')
    expect(afterSales?.searchParams.get('state')).toBe('PENDING_MERCHANT')
  })

  it('来源还有下一页时，条数写成下限「N+」，并说明还有未列出的事项', async () => {
    const alerts = page(
      [
        inventoryAlert('a-1', 'LOW_STOCK', '商品 1'),
        inventoryAlert('a-2', 'LOW_STOCK', '商品 2'),
        inventoryAlert('a-3', 'LOW_STOCK', '商品 3'),
      ],
      true,
    )
    const { wrapper } = await mountAttention({
      alerts: json(alerts),
      afterSales: json(page([])),
      signals: json(page([])),
    })
    expect(wrapper.get('[data-test=attention-filter-stock]').text()).toContain('3+')
    expect(wrapper.get('[data-test=attention-filter-all]').text()).toContain('3+')
    expect(wrapper.get('[data-test=attention-filter-after]').text()).not.toContain('+')

    await wrapper.get('[data-test=attention-filter-stock]').trigger('click')
    const overflow = wrapper.get('[data-test=attention-overflow]')
    expect(overflow.text()).toContain('还有更多未列出')
    expect(overflow.find('a').attributes('href')).toBe('/inventory')
  })

  it('超过 5 行且来源还有下一页时，写「还有至少 N 项」', async () => {
    const alerts = page(
      Array.from({ length: 7 }, (_, index) =>
        inventoryAlert(`a-${index}`, 'LOW_STOCK', `商品 ${index}`),
      ),
      true,
    )
    const { wrapper } = await mountAttention({
      alerts: json(alerts),
      afterSales: json(page([])),
      signals: json(page([])),
    })
    expect(wrapper.get('[data-test=attention-overflow]').text()).toContain('还有至少 2 项')
  })

  it('内容缺口只从信号第一页过滤：信号还有下一页时缺口条数同样写成下限', async () => {
    const { wrapper } = await mountAttention({ signals: json(page(defaultSignals.items, true)) })
    expect(wrapper.get('[data-test=attention-filter-gap]').text()).toContain('1+')
  })

  it('三个来源同时失败：只显示三条不可用说明，不显示空态或加载中', async () => {
    const { wrapper } = await mountAttention({
      alerts: failing(),
      afterSales: failing(),
      signals: failing(),
    })
    const notices = wrapper
      .findAll('[data-test=attention-unavailable]')
      .map((notice) => notice.text())
    expect(notices).toHaveLength(3)
    expect(notices.join(' ')).toContain('库存')
    expect(notices.join(' ')).toContain('售后')
    expect(notices.join(' ')).toContain('内容缺口')
    expect(wrapper.find('[data-test=attention-empty]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('正在汇总')
    expect(wrapper.findAll('[data-test=attention-row]')).toHaveLength(0)
  })

  it('按类别筛选：点「库存」只剩库存行，按钮上显示各类条数', async () => {
    const { wrapper } = await mountAttention()
    const stock = wrapper.get('[data-test=attention-filter-stock]')
    expect(stock.text()).toContain('2')

    await stock.trigger('click')

    expect(stock.attributes('aria-pressed')).toBe('true')
    const categories = wrapper
      .findAll('[data-test=attention-row]')
      .map((row) => row.attributes('data-category'))
    expect(categories).toEqual(['stock', 'stock'])
  })

  it('最多显示 5 行，其余用「还有 N 项」说明并可查看全部', async () => {
    const alerts = page(
      Array.from({ length: 7 }, (_, index) =>
        inventoryAlert(`a-${index}`, 'LOW_STOCK', `商品 ${index}`),
      ),
    )
    const { wrapper } = await mountAttention({
      alerts: json(alerts),
      afterSales: json(page([])),
      signals: json(page([])),
    })
    expect(wrapper.findAll('[data-test=attention-row]')).toHaveLength(5)
    expect(wrapper.get('[data-test=attention-overflow]').text()).toContain('还有 2 项')

    await wrapper.get('[data-test=attention-filter-stock]').trigger('click')
    expect(wrapper.get('[data-test=attention-overflow]').find('a').attributes('href')).toBe(
      '/inventory',
    )
  })

  it('售后来源失败只让售后一类不可用，库存与内容缺口照常显示', async () => {
    const { wrapper } = await mountAttention({ afterSales: failing() })

    expect(wrapper.findAll('[data-category=stock]')).toHaveLength(2)
    expect(wrapper.findAll('[data-category=gap]')).toHaveLength(1)
    expect(wrapper.findAll('[data-category=after]')).toHaveLength(0)
    const notices = wrapper
      .findAll('[data-test=attention-unavailable]')
      .map((notice) => notice.text())
    expect(notices).toHaveLength(1)
    expect(notices[0]).toContain('售后')

    await wrapper.get('[data-test=attention-filter-after]').trigger('click')
    expect(wrapper.get('[data-test=attention-unavailable]').text()).toContain('售后')
    expect(wrapper.find('[data-test=attention-empty]').exists()).toBe(false)
  })

  it('库存来源失败只让库存一类不可用', async () => {
    const { wrapper } = await mountAttention({ alerts: failing() })
    expect(wrapper.findAll('[data-category=stock]')).toHaveLength(0)
    expect(wrapper.findAll('[data-category=after]')).toHaveLength(1)
    expect(wrapper.findAll('[data-category=gap]')).toHaveLength(1)
    expect(wrapper.get('[data-test=attention-unavailable]').text()).toContain('库存')
  })

  it('某一类没有事项时显示空态', async () => {
    const { wrapper } = await mountAttention({ signals: json(page([])) })
    await wrapper.get('[data-test=attention-filter-gap]').trigger('click')
    expect(wrapper.get('[data-test=attention-empty]').text()).toContain('没有要处理的事')
  })

  it('行动按钮只预填问题并打开助手栏，不发请求', async () => {
    const { wrapper, fetchMock } = await mountAttention()
    const callsBefore = fetchMock.mock.calls.length

    await wrapper.get('[data-category=stock] [data-test=attention-ask]').trigger('click')

    expect(useOpsChatStore().pendingInput).toContain('轻量通勤夹克')
    expect(useRailStore().open).toBe(true)
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
  })
})
