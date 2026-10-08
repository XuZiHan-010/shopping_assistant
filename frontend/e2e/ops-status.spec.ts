import { expect, test } from '@playwright/test'

import { expectNoHorizontalOverflow } from './support/overflow'

/**
 * 只读运维看板（N5 B Task 3 步骤 3，D-N5-1）；取代两页合并时删除的 `ops-dashboard.spec.ts`。
 *
 * 走 Mock 传输层（`src/api/mock/transport.ts`）：证明的是页面行为——令牌闸门、只读、
 * 不外露凭证、窄屏不溢出。后端的鉴权与脱敏由 `backend/tests/api/test_admin_ops.py` 证明。
 */

const ADMIN_TOKEN = 'mock-admin-token'

async function enterWithAdminToken(page: import('@playwright/test').Page): Promise<void> {
  await page.getByLabel('管理员令牌').fill(ADMIN_TOKEN)
  await page.getByRole('button', { name: '进入后台' }).click()
  await expect(page.getByRole('heading', { name: '运维看板' })).toBeVisible()
}

test('运维看板需要管理员令牌，展示三级预算、成本、运行状况与 Chat BI，且只读', async ({ page }) => {
  await page.goto('/ops-status')

  // 没有令牌：只有令牌入口，受保护内容不渲染。
  await expect(page.getByRole('button', { name: '进入后台' })).toBeVisible()
  await expect(page.getByTestId('ops-budget')).toHaveCount(0)
  await expect(page.getByTestId('chatbi-overview')).toHaveCount(0)

  await enterWithAdminToken(page)

  const budget = page.getByTestId('ops-budget')
  await expect(budget.locator('tbody tr')).toHaveCount(4)
  await expect(budget).toContainText('ROLE:CUSTOMER')
  await expect(budget).toContainText('ROLE:MERCHANT')
  // 店铺级只显示后端给的脱敏标识。
  await expect(budget).toContainText('SHOP:MERCHANT:1a2b3c4d')

  await expect(page.getByTestId('ops-cost')).toContainText('0.00075000 USD')
  await expect(page.getByTestId('ops-cost')).toContainText('20%')
  // 每回合 token、成本、耗时，以及降级原因（验收 §12.6）。
  await expect(page.getByTestId('ops-turns')).toContainText('400')
  await expect(page.getByTestId('ops-turns')).toContainText('0.00025000 USD')
  await expect(page.getByTestId('ops-turns')).toContainText('2,250 ms')
  await expect(page.getByTestId('ops-degraded-reasons')).toContainText('每日预算耗尽')
  await expect(page.getByTestId('ops-source-degradations')).toContainText('KNOWLEDGE')
  await expect(page.getByTestId('ops-runtime')).toContainText('10%')
  await expect(page.getByTestId('ops-routes')).toContainText('/api/v2/merchant/chat')
  await expect(page.getByTestId('chatbi-overview')).toContainText('2026-08-17 至 2026-08-23')
  await expect(page.getByTestId('chatbi-daily').locator('tbody tr')).toHaveCount(2)

  // 只读：主视图里除「刷新」外没有任何按钮，也没有 Chat BI 手动回补入口。
  const main = page.locator('main#main')
  await expect(main.getByRole('button')).toHaveText(['刷新'])
  await expect(main).not.toContainText(/回补|rollup|recompute/i)

  // 凭证不进页面内容，也不进地址栏。
  await expect(page.locator('body')).not.toContainText(ADMIN_TOKEN)
  expect(page.url()).not.toContain(ADMIN_TOKEN)

  // 侧栏「管理」分组的入口指向本页并处于当前态。
  await expect(page.getByRole('link', { name: '运维看板' })).toHaveAttribute('aria-current', 'page')
})

test('英语下页头与分区标题为英语', async ({ page }) => {
  await page.goto('/ops-status')
  await enterWithAdminToken(page)

  await page.getByTestId('preferences-trigger').click()
  await page.locator('select[name="language"]').selectOption('en-US')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  await page.keyboard.press('Escape')

  await expect(page.getByRole('heading', { name: 'Operations status' })).toBeVisible()
  await expect(page.getByTestId('ops-budget')).toContainText("Today's budget")
  await expect(page.locator('main#main').getByRole('button')).toHaveText(['Refresh'])
})

test('375px 下运维看板不产生横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/ops-status')
  await enterWithAdminToken(page)
  await expect(page.getByTestId('chatbi-daily')).toBeVisible()

  await expectNoHorizontalOverflow(page, '运维看板 375px')
})
