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

    // 两页合并（2026-09-27，选项 C）后 `/` 是 v2 运营助手：身份换取与会话
    // 目录走 `/api/v2/merchant/*`，取代了 v1 的 `/api/conversations`。
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

  await page.goto('/')
  await expect(page.getByLabel('向运营助手提问')).toBeVisible()
  await expect
    .poll(() => interceptedApiPaths)
    .toEqual(['/api/demo/merchants', '/api/v2/merchant/sessions', '/api/v2/merchant/conversations'])

  expect(requested).toEqual([])
})
