/**
 * 订单页与商品页 Mock E2E（W Task 9）：列表、筛选（换筛选不带旧游标）、游标翻页、
 * 详情抽屉（价格快照、三个状态维度、Esc 关闭焦点回到触发行）、375px 无横向溢出、
 * 商品页缺口标签来自后端与「问助手」只预填。
 */
import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

import { mockOpsAssistantShell } from './support/v2MerchantMock'
import { expectNoHorizontalOverflow } from './support/overflow'
import { mockCatalogPage, mockOrdersPage } from './support/workspaceMock'

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test('订单页：列表、筛选、翻页，换筛选从不带旧游标', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await mockOpsAssistantShell(page)
  const log = await mockOrdersPage(page)

  await page.goto('/orders')
  await expect(page.getByRole('heading', { level: 1, name: '订单' })).toBeVisible()
  await expect(page.locator('[data-test=orders-scope]')).toContainText('平台交易')
  const rows = page.locator('[data-test=order-row]')
  await expect(rows).toHaveCount(3)
  await expect(rows.first()).toContainText('顾客 R5T1')

  await page.locator('[data-test=orders-load-more]').click()
  await expect(rows).toHaveCount(5)
  await expect(page.locator('[data-test=orders-load-more]')).toHaveCount(0)
  expect(log.listRequests.at(-1)!.searchParams.get('cursor')).not.toBeNull()

  await page.getByLabel('支付状态').selectOption('PENDING')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('顾客 P2Q9')
  const filteredRequest = log.listRequests.at(-1)!
  expect(filteredRequest.searchParams.get('payment_status')).toBe('PENDING')
  expect(filteredRequest.searchParams.get('cursor')).toBeNull()

  await page.locator('[data-test=filters-clear]').click()
  await expect(rows).toHaveCount(3)
  await page.getByLabel('售后状态').selectOption('ACTIVE')
  await expect(rows).toHaveCount(1)
  await expect(rows.first()).toContainText('售后中')

  expect(log.invalidCursorRequests).toEqual([])
  expect(errors).toEqual([])
})

test('订单详情抽屉：价格快照与三个状态维度，Esc 关闭后焦点回到该订单', async ({ page }) => {
  await mockOpsAssistantShell(page)
  await mockOrdersPage(page)

  await page.goto('/orders')
  const trigger = page.locator('[data-test=order-open]').nth(2)
  await trigger.click()

  const dialog = page.getByRole('dialog', { name: '订单详情' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('价格快照')
  await expect(dialog.locator('[data-test=snapshot-line]')).toContainText('轻量通勤夹克')
  await expect(dialog.locator('[data-test=status-payment]')).toContainText('已支付')
  await expect(dialog.locator('[data-test=status-fulfillment]')).toContainText('运输中')
  await expect(dialog.locator('[data-test=status-after-sale]')).toContainText('无售后')
  await expect(dialog.locator('[data-test=buyer-alias]')).toContainText('顾客 K3F9')
  await expect(dialog.getByRole('button')).toHaveCount(1)
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)

  // 模态抽屉打开时 Ctrl + J 不切换助手栏，焦点仍留在抽屉里。
  await page.keyboard.press('Control+j')
  await expect(page.getByTestId('merchant-shell')).toHaveAttribute('data-rail', 'closed')
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('375px 浅色与深色：订单列表、详情抽屉与商品页都没有横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await mockOpsAssistantShell(page)
  await mockOrdersPage(page)
  await mockCatalogPage(page)

  await page.goto('/orders')
  await expect(page.locator('[data-test=order-row]')).toHaveCount(3)
  await expectNoHorizontalOverflow(page, '375px 订单列表')

  await page.locator('[data-test=order-open]').first().click()
  const dialog = page.getByRole('dialog', { name: '订单详情' })
  await expect(dialog.locator('[data-test=snapshot-line]')).toBeVisible()
  await expectNoHorizontalOverflow(page, '375px 订单详情抽屉')
  const box = await dialog.boundingBox()
  expect(box!.x).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width).toBeLessThanOrEqual(375)
  await page.keyboard.press('Escape')

  await page.evaluate(() => window.localStorage.setItem('borough.theme', 'dark'))
  await page.goto('/catalog')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await expect(page.locator('[data-test=product-row]')).toHaveCount(3)
  await expectNoHorizontalOverflow(page, '375px 深色商品页')
  const panelBackground = await page.evaluate(
    () => getComputedStyle(document.querySelector('[data-test=product-row]')!.closest('.ws-panel')!)
      .backgroundColor,
  )
  expect(panelBackground).not.toBe('rgb(255, 255, 255)')
})

test('商品页：缺口标签来自后端，「起草补充」只预填助手不发送', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await mockOpsAssistantShell(page)
  await mockCatalogPage(page)
  let chatRequests = 0
  await page.route('**/api/v2/merchant/chat', async (route) => {
    chatRequests += 1
    await route.abort()
  })

  await page.goto('/catalog')
  const rows = page.locator('[data-test=product-row]')
  await expect(rows).toHaveCount(3)
  await expect(rows.nth(0).locator('[data-test=gap-tag]')).toHaveText(['缺面料成分', '缺商品图片'])
  await expect(rows.nth(1).locator('[data-test=content-complete]')).toBeVisible()
  await expect(rows.nth(2).locator('[data-test=gap-tag]')).toHaveText(['缺商品描述'])

  await rows.nth(0).locator('[data-test=product-ask]').click()
  const input = page.getByRole('textbox', { name: '向运营助手提问' })
  await expect(input).toHaveValue('帮我给「轻量通勤夹克（M 码）」起草内容补充，缺：面料成分、商品图片')
  await expect(page).toHaveURL(/\/catalog$/)
  expect(chatRequests).toBe(0)
  expect(errors).toEqual([])
})
