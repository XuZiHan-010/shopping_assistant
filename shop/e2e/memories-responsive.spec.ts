/** N4 B 顾客记忆页：375px 无横向溢出，关闭前必须二次确认。 */
import { expect, test, type Page } from '@playwright/test'

test.use({ viewport: { width: 375, height: 812 } })

async function noOverflow(page: Page) {
  const widths = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth, viewport: window.innerWidth,
  }))
  expect(widths.page).toBeLessThanOrEqual(widths.viewport)
}

test('访客提示、绑定后管理与关闭确认在窄屏可用', async ({ page }) => {
  await page.goto('/borough-s1-e2e')
  await page.getByRole('button', { name: '动态' }).click()
  const drawer = page.getByRole('dialog', { name: '动态' })
  await drawer.getByRole('tab', { name: '我记住的' }).click()
  await expect(drawer.getByText('记忆只对绑定的演示顾客开放。')).toBeVisible()
  await noOverflow(page)

  await drawer.getByRole('button', { name: '绑定演示顾客' }).click()
  await expect(drawer.getByRole('switch', { name: '允许智能助手记住我的偏好' })).toBeVisible()
  await noOverflow(page)
  await drawer.getByRole('switch', { name: '允许智能助手记住我的偏好' }).click()
  await expect(drawer.getByRole('group', { name: /关闭记忆会清空/ })).toBeVisible()
  await noOverflow(page)
  await drawer.getByRole('button', { name: '取消' }).click()
  await expect(drawer.getByRole('group', { name: /关闭记忆会清空/ })).toHaveCount(0)
  await expect(drawer.getByRole('switch', { name: '允许智能助手记住我的偏好' })).toHaveAttribute('aria-checked', 'true')
})
