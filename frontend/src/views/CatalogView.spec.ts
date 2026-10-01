/**
 * 商品页（W Task 9，契约 §8.12.3 `GET /api/v2/merchant/products/content`）：
 * 内容完整度与缺口标签逐字来自后端（R4/R7），页面不自行判定缺口；
 * 「问助手」只预填不发送；空态、错误与重试、翻页。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { setLocaleProvider } from '@/api/credentials'
import { useLocaleStore } from '@/stores/locale'
import { useOpsChatStore } from '@/stores/opsChat'
import { useRailStore } from '@/stores/rail'
import {
  failing,
  json,
  pinnedSessionPinia,
  routeFetch,
  TEST_BASE_URL,
  type RouteHandler,
} from '@/testing/homeHarness'
import { errorResponse, jsonResponse, page } from '@/testing/homePayloads'
import { productContent } from '@/testing/workspacePayloads'

import CatalogView from './CatalogView.vue'

const CONTENT = '/api/v2/merchant/products/content'

async function mountCatalog(handler: RouteHandler) {
  const pinia = pinnedSessionPinia()
  const fetchMock = vi.fn(routeFetch([[CONTENT, handler]]))
  vi.stubGlobal('fetch', fetchMock)
  const wrapper = mount(CatalogView, {
    attachTo: document.body,
    global: { plugins: [pinia, i18n] },
  })
  await flushPromises()
  return { wrapper, fetchMock }
}

beforeEach(() => {
  setLocaleProvider(() => useLocaleStore().locale)
  vi.stubEnv('VITE_API_BASE_URL', TEST_BASE_URL)
})

afterEach(() => {
  setLocaleProvider(undefined)
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  i18n.global.locale.value = 'zh-CN'
  document.body.innerHTML = ''
})

describe('CatalogView', () => {
  it('切语言使分页从第一页重新开始，不使用旧语言游标', async () => {
    const { wrapper, fetchMock } = await mountCatalog((_url, init) =>
      jsonResponse(
        page(
          [
            productContent('p-1', {
              title:
                new Headers(init?.headers).get('Accept-Language') === 'en-US'
                  ? 'Fresh content'
                  : '原内容',
            }),
          ],
          true,
        ),
      ),
    )
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    expect(wrapper.text()).toContain('Fresh content')
    expect(fetchMock.mock.calls).toHaveLength(2)
    expect(new URL(String(fetchMock.mock.calls[1]![0])).searchParams.get('cursor')).toBeNull()
    wrapper.unmount()
  })
  it('请求 products/content 第一页，每行显示商品、类目、可售与状态', async () => {
    const { wrapper, fetchMock } = await mountCatalog(
      json(page([productContent('p-1', { title: '轻量通勤夹克', stock_available: 7 })])),
    )
    const url = new URL(String(fetchMock.mock.calls[0]![0]))
    expect(url.pathname).toBe(CONTENT)
    expect(url.searchParams.get('cursor')).toBeNull()

    expect(wrapper.get('h1').text()).toBe('商品')
    const row = wrapper.get('[data-test=product-row]')
    expect(row.text()).toContain('轻量通勤夹克')
    expect(row.text()).toContain('男装')
    expect(row.text()).toContain('7')
    expect(row.text()).toContain('在售')
  })

  it('完整度与缺口标签逐字来自后端，顺序不变', async () => {
    const { wrapper } = await mountCatalog(
      json(
        page([
          productContent('p-1', { title: '完整的商品' }),
          productContent('p-2', {
            title: '缺内容的商品',
            content_complete: false,
            missing_required_attributes: ['面料成分', '洗涤说明'],
            missing_content_fields: ['商品描述', '商品图片'],
          }),
        ]),
      ),
    )
    const rows = wrapper.findAll('[data-test=product-row]')
    expect(rows[0]!.get('[data-test=content-complete]').text()).toContain('内容完整')
    expect(rows[0]!.findAll('[data-test=gap-tag]')).toHaveLength(0)

    const tags = rows[1]!.findAll('[data-test=gap-tag]').map((tag) => tag.text())
    expect(tags).toEqual(['缺面料成分', '缺洗涤说明', '缺商品描述', '缺商品图片'])
    expect(rows[1]!.find('[data-test=content-complete]').exists()).toBe(false)
  })

  it('页面不自行判定缺口：只看 content_complete 与两个缺口数组', async () => {
    // 后端说不完整但没列出缺口（契约里不应出现，这里验证页面不“补判”）：只显示不完整，不编造标签。
    const { wrapper } = await mountCatalog(
      json(page([productContent('p-1', { content_complete: false })])),
    )
    const row = wrapper.get('[data-test=product-row]')
    expect(row.get('[data-test=content-incomplete]').text()).toContain('内容不完整')
    expect(row.findAll('[data-test=gap-tag]')).toHaveLength(0)
  })

  it('英文界面下已知内容字段翻译，类目属性名保持后端原文', async () => {
    const { wrapper } = await mountCatalog(
      json(
        page([
          productContent('p-1', {
            content_complete: false,
            missing_required_attributes: ['面料成分'],
            missing_content_fields: ['商品描述'],
          }),
        ]),
      ),
    )
    useLocaleStore().setLocale('en-US')
    await flushPromises()
    const tags = wrapper.findAll('[data-test=gap-tag]').map((tag) => tag.text())
    expect(tags).toEqual(['Missing 面料成分', 'Missing description'])
  })

  it('「检查内容缺口」与行内「起草补充」只预填助手并打开助手栏，不发送', async () => {
    const { wrapper, fetchMock } = await mountCatalog(
      json(
        page([
          productContent('p-1', {
            title: '轻量通勤夹克',
            content_complete: false,
            missing_required_attributes: ['面料成分'],
            missing_content_fields: ['商品图片'],
          }),
        ]),
      ),
    )
    await wrapper.get('[data-test=catalog-ask]').trigger('click')
    expect(useOpsChatStore().pendingInput).toBe('哪些商品的详情页信息不完整？帮我按影响排序')
    expect(useRailStore().open).toBe(true)

    await wrapper.get('[data-test=product-ask]').trigger('click')
    expect(useOpsChatStore().pendingInput).toBe(
      '帮我给「轻量通勤夹克」起草内容补充，缺：面料成分、商品图片',
    )
    expect(fetchMock.mock.calls.every((call) => !String(call[0]).includes('/chat'))).toBe(true)
  })

  it('内容完整的商品没有「起草补充」', async () => {
    const { wrapper } = await mountCatalog(json(page([productContent('p-1')])))
    expect(wrapper.find('[data-test=product-ask]').exists()).toBe(false)
  })

  it('加载更多带上游标并追加', async () => {
    const { wrapper, fetchMock } = await mountCatalog((url) =>
      url.searchParams.get('cursor') === 'cursor-next'
        ? jsonResponse(page([productContent('p-2')]))
        : jsonResponse(page([productContent('p-1')], true)),
    )
    await wrapper.get('[data-test=catalog-load-more]').trigger('click')
    await flushPromises()

    const last = new URL(String(fetchMock.mock.calls.at(-1)![0]))
    expect(last.searchParams.get('cursor')).toBe('cursor-next')
    expect(wrapper.findAll('[data-test=product-row]')).toHaveLength(2)
    expect(wrapper.find('[data-test=catalog-load-more]').exists()).toBe(false)
  })

  it('「加载更多」失败时保留已加载的商品，并可再试', async () => {
    let fail = true
    const { wrapper } = await mountCatalog((url, init) => {
      if (url.searchParams.get('cursor')) {
        return fail ? failing()(url, init) : jsonResponse(page([productContent('p-2')]))
      }
      return jsonResponse(page([productContent('p-1')], true))
    })
    await wrapper.get('[data-test=catalog-load-more]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=product-row]')).toHaveLength(1)
    expect(wrapper.get('[role=alert]').text()).toContain('更多商品暂时无法读取')

    fail = false
    await wrapper.get('[data-test=catalog-load-more]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=product-row]')).toHaveLength(2)
  })

  it('「加载更多」遇到 INVALID_CURSOR（换语言或游标过期）时从第一页重读，并礼貌提示', async () => {
    const { wrapper, fetchMock } = await mountCatalog((url) => {
      if (url.searchParams.get('cursor')) return errorResponse(422, 'INVALID_CURSOR')
      return jsonResponse(page([productContent('p-1')], true))
    })
    const loadMore = wrapper.get('[data-test=catalog-load-more]')
    ;(loadMore.element as HTMLElement).focus()
    await loadMore.trigger('click')
    await flushPromises()

    const urls = fetchMock.mock.calls.map((call) => new URL(String(call[0])))
    expect(urls).toHaveLength(3)
    expect(urls[1]!.searchParams.get('cursor')).toBe('cursor-next')
    expect(urls[2]!.searchParams.get('cursor')).toBeNull()
    expect(wrapper.findAll('[data-test=product-row]')).toHaveLength(1)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    const notice = wrapper.get('[data-test=catalog-restarted]')
    expect(notice.element.closest('[role=status]')).not.toBeNull()
    expect(notice.text()).toContain('已从第一页重新加载')
    expect(document.activeElement).toBe(wrapper.get('[data-test=catalog-panel]').element)

    // 再点「加载更多」用的是新第一页签发的游标，而不是那枚失效游标重试。
    expect(wrapper.find('[data-test=catalog-load-more]').exists()).toBe(true)
  })

  it('没有商品时显示空态', async () => {
    const { wrapper } = await mountCatalog(json(page([])))
    expect(wrapper.get('[data-test=catalog-empty]').text()).toContain('还没有商品')
  })

  it('读取失败显示错误与重试，重试成功后显示商品', async () => {
    let fail = true
    const { wrapper } = await mountCatalog((url, init) =>
      fail ? failing()(url, init) : json(page([productContent('p-1')]))(url, init),
    )
    expect(wrapper.get('[role=alert]').text()).toContain('商品内容暂时无法读取')

    fail = false
    await wrapper.get('[data-test=catalog-retry]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test=product-row]')).toHaveLength(1)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.get('[data-test=catalog-panel]').element)
  })
})
