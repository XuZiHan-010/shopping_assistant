/**
 * 首页 Mock E2E（W Task 8）：四个区块在真实浏览器里渲染、空闲后才取数并挂载趋势图、
 * 375px 无横向溢出、深色模式走 token、中英双语与「问助手」只预填。
 *
 * 首页数据走 `mockOpsAssistantShell()` 里的 `mockHomeEndpoints()`（固定演示载荷）；
 * 首屏请求序列的门禁在 `first-paint.spec.ts`（冻结空闲回调），这里不重复。
 */
import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

import { switchLanguage } from './support/assistantRail'
import { mockOpsAssistantShell } from './support/v2MerchantMock'
import { expectNoHorizontalOverflow } from './support/overflow'

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test('首页四个区块渲染真实载荷，空闲后挂载趋势图，无控制台错误', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  const echartsRequests: string[] = []
  page.on('request', (request) => {
    if (/echarts/.test(request.url())) echartsRequests.push(request.url())
  })
  await mockOpsAssistantShell(page)

  await page.goto('/')

  const brief = page.getByRole('region', { name: '今日简报' })
  await expect(brief.getByRole('heading', { name: '今日简报' })).toBeVisible()
  await expect(brief).toContainText('库存偏低：轻量通勤夹克（M 码）')
  await expect(brief).toContainText('暂无待批准草稿。')
  await expect(page.locator('[data-test=metric-value]')).toHaveText('¥12,345.00')
  await expect(page.locator('[data-test=metric-change]')).toHaveText('-5%')
  await expect(page.locator('[data-test=attention-row]')).toHaveCount(1)
  await expect(page.locator('[data-test=recent-order]')).toContainText('顾客 R5T1')
  await expect(page.locator('[data-test=metric-order-scope]')).toContainText('历史导入订单')
  // 趋势图懒加载：空闲且可见后挂载，canvas 出现、ECharts chunk 被请求。
  await expect(page.locator('[data-test=home-trend-chart] canvas')).toBeVisible()
  expect(echartsRequests.length).toBeGreaterThan(0)
  await expect(page.locator('body')).not.toContainText(/AI\s*分析/)

  expect(errors).toEqual([])
})

test('简报「问助手」与辅助指标只预填问题并打开助手栏，不跳页、不发送', async ({ page }) => {
  await mockOpsAssistantShell(page)
  let chatRequests = 0
  await page.route('**/api/v2/merchant/chat', async (route) => {
    chatRequests += 1
    await route.abort()
  })

  await page.goto('/')
  await page.locator('[data-test=next-action]').click()

  const input = page.getByRole('textbox', { name: '向运营助手提问' })
  await expect(input).toHaveValue('给「轻量通勤夹克」起草补货')
  await expect(page).toHaveURL(/\/$/)

  await page.keyboard.press('Escape')
  await page.locator('[data-test=secondary-metric]').nth(1).click()
  await expect(input).toHaveValue(/退款金额/)
  expect(chatRequests).toBe(0)
})

test('375px 浅色与深色下首页都没有横向溢出，深色卡片不是白底', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await mockOpsAssistantShell(page)

  await page.goto('/')
  await expect(page.locator('[data-test=recent-order]')).toBeVisible()
  await expect(page.locator('[data-test=metric-value]')).toBeVisible()
  await expectNoHorizontalOverflow(page, '375px 浅色首页')

  await page.evaluate(() => window.localStorage.setItem('borough.theme', 'dark'))
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('[data-test=metric-value]')).toBeVisible()
  await expectNoHorizontalOverflow(page, '375px 深色首页')
  const backgrounds = await page.evaluate(() =>
    ['[data-test=home-metric]', '[data-test=home-attention]', '[data-test=home-recent-orders]'].map(
      (selector) => getComputedStyle(document.querySelector(selector)!).backgroundColor,
    ),
  )
  for (const background of backgrounds) expect(background).not.toBe('rgb(255, 255, 255)')
})

test('切到英语后首页区块标题与口径说明为英文', async ({ page }) => {
  await mockOpsAssistantShell(page)

  await page.goto('/')
  await expect(page.locator('[data-test=metric-value]')).toBeVisible()
  await switchLanguage(page, 'en-US')

  await expect(page.getByRole('heading', { name: "Today's brief" })).toBeVisible()
  await expect(page.getByRole('heading', { name: /Net sales/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Needs you today' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Recent orders' })).toBeVisible()
  await expect(page.locator('[data-test=metric-order-scope]')).toContainText(
    'include imported historical orders',
  )
})
