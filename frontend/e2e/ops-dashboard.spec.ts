import { expect, test } from '@playwright/test'

test.describe('Chat BI 看板', () => {
  test('未授权时只显示令牌对话框', async ({ page }) => {
    await page.goto('/ops-dashboard')

    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByTestId('north-star-card')).toHaveCount(0)
  })

  test('授权后显示六项指标与分类下钻', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('mock-admin-token')
    await page.getByRole('button', { name: '进入后台' }).click()

    await expect(page.getByTestId('north-star-card')).toHaveCount(6)
    await expect(
      page.getByTestId('north-star-card').filter({ hasText: '用户侧准确率' }),
    ).toBeVisible()
    await expect(
      page.getByTestId('north-star-card').filter({ hasText: '系统侧准确率' }),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: '按问题分类查看表现' })).toBeVisible()
  })

  test('样本不足时展示说明而不伪造零比率', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('mock-admin-token')
    await page.getByRole('button', { name: '进入后台' }).click()

    await expect(page.getByText('样本不足').first()).toBeVisible()
  })
})
