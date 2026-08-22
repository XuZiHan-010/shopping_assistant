import { expect, test } from '@playwright/test'

test('知识库后台需要令牌，支持编辑团队文档且记忆只读', async ({ page }) => {
  await page.goto('/knowledge-base')

  await expect(page.getByRole('heading', { name: '知识库维护后台' })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入后台' })).toBeVisible()
  await expect(page.getByText('知识目录')).toHaveCount(0)

  await page.getByLabel('管理员令牌').fill('mock-admin-token')
  await page.getByRole('button', { name: '进入后台' }).click()

  await expect(page.getByText('知识目录', { exact: true })).toBeVisible()
  await expect(page.locator('[data-path="index"]')).toBeVisible()
  await expect(page.locator('[data-path="业务"]')).toBeVisible()
  await expect(page.locator('[data-path="memory"]')).toBeVisible()

  await page.locator('[data-path="index/运营手册.md"]').click()
  const editor = page.getByRole('textbox', { name: 'index/运营手册.md 内容' })
  await expect(editor).toBeVisible()
  await editor.fill('# 运营手册\n\n已编辑内容')
  await page.getByTestId('save').click()
  await expect(editor).toHaveValue('# 运营手册\n\n已编辑内容')

  await page.locator('[data-path="memory/merchants/demo/TRADE.md"]').click()
  const memoryEditor = page.getByRole('textbox', { name: 'memory/merchants/demo/TRADE.md 内容' })
  await expect(memoryEditor).toHaveAttribute('readonly', '')
  await expect(page.getByTestId('save')).toHaveCount(0)
})
