/**
 * 「顾客视角」单入口（N5 E Task 2，D-N5-4）：登录后侧栏出现入口，点击在新标签页打开本店顾客端。
 *
 * 入口只是链接：新标签的地址里没有会话 ID、演示 Token 或查询参数，请求不带来源地址，
 * 新页面也拿不到 `window.opener`。顾客端域名是占位值，由浏览器上下文拦截。
 */
import { expect, test } from '@playwright/test'

import { expectNoHorizontalOverflow } from './support/overflow'
import {
  MOCK_DEMO_TOKENS,
  MOCK_SHOP_BASE_URL,
  MOCK_SHOP_SLUG,
  mockOpsAssistantShell,
  mockSessionIdFor,
} from './support/v2MerchantMock'

const SHOP_URL = `${MOCK_SHOP_BASE_URL}/${MOCK_SHOP_SLUG}`

test('登录后「顾客视角」在新标签页打开本店顾客端，不带任何凭证', async ({ page, context }) => {
  const shopRequests: { url: string; referer: string | undefined }[] = []
  await context.route(`${MOCK_SHOP_BASE_URL}/**`, async (route) => {
    shopRequests.push({ url: route.request().url(), referer: route.request().headers()['referer'] })
    await route.fulfill({ contentType: 'text/html', body: '<title>shop</title><h1>顾客端占位页</h1>' })
  })
  await mockOpsAssistantShell(page)

  await page.goto('/')

  const entry = page.getByTestId('customer-view-link')
  await expect(entry).toBeVisible()
  await expect(entry).toHaveText('顾客视角')
  await expect(entry).toHaveAttribute('href', SHOP_URL)
  await expect(entry).toHaveAttribute('target', '_blank')
  await expect(entry).toHaveAttribute('rel', /noopener/)
  await expect(entry).toHaveAttribute('rel', /noreferrer/)

  const [shopPage] = await Promise.all([context.waitForEvent('page'), entry.click()])
  await shopPage.waitForLoadState()

  expect(shopPage.url()).toBe(SHOP_URL)
  expect(await shopPage.evaluate(() => window.opener)).toBeNull()
  expect(shopRequests).toHaveLength(1)
  expect(shopRequests[0]!.referer).toBeUndefined()
  for (const token of Object.values(MOCK_DEMO_TOKENS)) {
    expect(shopRequests[0]!.url).not.toContain(token)
    expect(shopRequests[0]!.url).not.toContain(mockSessionIdFor(token))
  }
  // 商家端标签页留在原处。
  expect(new URL(page.url()).pathname).toBe('/')
})

test('375px：侧栏抽屉里有「顾客视角」入口，且不产生横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await mockOpsAssistantShell(page)
  await page.goto('/')

  await page.locator('[aria-controls="side-nav"]').click()
  await expect(page.getByTestId('customer-view-link')).toBeVisible()

  await expectNoHorizontalOverflow(page, '侧栏抽屉 + 顾客视角 375px')
})
