import { afterEach, describe, expect, it, vi } from 'vitest'
import { getProduct, listProducts } from './catalogApi'

afterEach(() => vi.unstubAllGlobals())

describe('公开商品请求语言', () => {
  it('英文商品列表与详情都把页面语言传给后端', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', 'https://api.example.test')
    const seen: RequestInit[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) => {
      seen.push(options)
      const product = {
        id: 'p1', name: 'Scarf', short_description: '', price_cents: 100,
        stock_band: 'IN_STOCK', image_url: null, source_locale: 'zh-CN', content_version: 1,
        requested_locale: 'en-US', name_translation_status: 'MACHINE', short_description_translation_status: 'SOURCE',
        description: '', description_translation_status: 'SOURCE', attributes: [],
      }
      return new Response(JSON.stringify(seen.length === 1 ? { items: [product], has_more: false, next_cursor: null } : product), { status: 200 })
    }))

    await listProducts('borough-100', 'en-US')
    await getProduct('borough-100', 'p1', 'en-US')
    expect(seen.map((options) => (options.headers as Record<string, string>)['Accept-Language'])).toEqual(['en-US', 'en-US'])
  })
})
