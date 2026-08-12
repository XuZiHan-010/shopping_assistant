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

    if (request.method() === 'GET' && url.pathname === '/api/conversations') {
      await route.fulfill({ headers, json: { items: [], limit: 50, offset: 0 } })
      return
    }

    await route.fulfill({ headers, status: 404, json: { detail: '首屏测试未允许该请求' } })
  })

  await page.goto('/')
  await expect(page.getByTestId('quick-question').first()).toBeVisible()
  await expect
    .poll(() => interceptedApiPaths)
    .toEqual(['/api/demo/merchants', '/api/conversations'])

  expect(requested).toEqual([])
})
