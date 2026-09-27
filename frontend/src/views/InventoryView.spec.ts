import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import InventoryView from './InventoryView.vue'

const BASE_URL = 'http://127.0.0.1:8000'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function alert(overrides: Record<string, unknown> = {}) {
  return {
    id: 'LOW_STOCK:p-1',
    kind: 'LOW_STOCK',
    product_id: 'p-1',
    product_name: '测试商品',
    stock_on_hand: 6,
    stock_reserved: 2,
    stock_available: 4,
    low_stock_threshold: 5,
    sold_last_30d: 12,
    days_of_supply: 10,
    ...overrides,
  }
}

async function mountInventory(alerts = [alert()]) {
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

  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      if (url.includes('/products/content')) {
        return Promise.resolve(jsonResponse({
          items: [{
            id: 'p-content', title: '待补资料连衣裙', category: '女装', status: 'ONLINE',
            content_version: 2, missing_required_attributes: ['产地'],
            missing_content_fields: ['商品图片'], content_complete: false,
            stock_on_hand: 8, stock_reserved: 2, stock_available: 6,
          }], next_cursor: null, has_more: false,
        }))
      }
      if (url.includes('/merchant/coupons')) {
        return Promise.resolve(jsonResponse({
          items: [{
            id: 'coupon-1', name: '九折券', kind: 'PERCENT_OFF', state: 'INACTIVE',
            currently_active: false, min_spend_cents: 0, amount_off_cents: null,
            discount_bps: 9000, product_ids: [], starts_at: '2026-09-01T00:00:00Z',
            ends_at: '2026-10-01T00:00:00Z',
          }], next_cursor: null, has_more: false,
        }))
      }
      return Promise.resolve(jsonResponse({ items: alerts, next_cursor: null, has_more: false }))
    }),
  )

  const wrapper = mount(InventoryView, { global: { plugins: [pinia, i18n] } })
  await flushPromises()
  return { wrapper }
}

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('InventoryView', () => {
  it('展示在库、占用、可售、30 天销量与告警类型', async () => {
    const { wrapper } = await mountInventory()
    const text = wrapper.text()
    expect(text).toContain('测试商品')
    expect(text).toContain('6') // stock_on_hand
    expect(text).toContain('4') // stock_available
    expect(text).toContain('12') // sold_last_30d
  })

  it('可售天数为「未知」时显示提示文案，不显示数字', async () => {
    const { wrapper } = await mountInventory([alert({ sold_last_30d: 0, days_of_supply: null })])
    const text = wrapper.text()
    expect(text).toContain('未知')
    expect(text).not.toMatch(/可售天数[^未]*0天/)
  })

  it('展示后端判定的商品内容缺口和停用优惠券', async () => {
    const { wrapper } = await mountInventory()
    expect(wrapper.text()).toContain('待补资料连衣裙')
    expect(wrapper.text()).toContain('产地')
    expect(wrapper.text()).toContain('商品图片')
    expect(wrapper.text()).toContain('九折券')
    expect(wrapper.text()).toContain('未生效')
    expect(wrapper.text()).toContain('优惠 10%')
  })
})
