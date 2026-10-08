import { expect, test } from '@playwright/test'

test('首屏不请求 ECharts chunk', async ({ page }) => {
  const requested: string[] = []
  const interceptedApiPaths: string[] = []

  // 首屏门禁只观察首次可交互画面。冻结 idle 回调，而不是用固定时长赌
  // 调度顺序；运行时仍由浏览器在空闲后挂载图表。
  await page.addInitScript(() => {
    window.requestIdleCallback = () => 1
  })

  page.on('request', (request) => {
    const url = request.url()
    if (/\/assets\/echarts-[^/]*\.js$/.test(url)) requested.push(url)
  })

  await page.route('http://borough-preview.test/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    interceptedApiPaths.push(url.pathname)
    const headers = {
      'access-control-allow-origin': new URL(page.url()).origin,
      'content-type': 'application/json',
    }

    if (request.method() === 'GET' && url.pathname === '/api/demo/merchants') {
      await route.fulfill({
        headers,
        json: {
          merchants: [
            {
              merchant_id: 'merchant-100',
              display_name: 'Borough商家100',
              token: 'first-paint-demo-token',
            },
          ],
        },
      })
      return
    }

    // 身份换取与助手栏会话目录走 `/api/v2/merchant/*`（W 阶段起 `/` 是首页，
    // 运营助手是常驻外壳的助手栏），取代了 v1 的 `/api/conversations`。
    if (request.method() === 'POST' && url.pathname === '/api/v2/merchant/sessions') {
      await route.fulfill({
        headers,
        status: 201,
        json: {
          session_id: 'first-paint-session-id-00000000000000000000',
          role: 'MERCHANT',
          expires_at: '2099-01-01T00:00:00Z',
          merchant_display_name: 'Borough商家100',
        },
      })
      return
    }

    if (request.method() === 'GET' && url.pathname === '/api/v2/merchant/conversations') {
      await route.fulfill({ headers, json: { items: [], next_cursor: null, has_more: false } })
      return
    }

    await route.fulfill({ headers, status: 404, json: { detail: '首屏测试未允许该请求' } })
  })

  // W Task 6：运营助手是默认收起的助手栏，从 `/?assistant=open`（`/ops-assistant` 的落点）进入。
  await page.goto('/?assistant=open')
  await expect(page.getByLabel('向运营助手提问')).toBeVisible()
  await expect
    .poll(() => interceptedApiPaths)
    .toEqual(['/api/demo/merchants', '/api/v2/merchant/sessions', '/api/v2/merchant/conversations'])

  // W Task 8：`/` 是首页。首屏只画出区块骨架，简报、主指标、订单等取数与趋势图都推迟到
  // 空闲之后（这里空闲回调被冻结），所以请求序列仍然只有上面三条。
  await expect(page.getByRole('heading', { name: '今日简报' })).toBeVisible()
  await expect(page.locator('[data-test=home-metric]')).toBeVisible()
  expect(interceptedApiPaths).toEqual([
    '/api/demo/merchants',
    '/api/v2/merchant/sessions',
    '/api/v2/merchant/conversations',
  ])

  expect(requested).toEqual([])
})
