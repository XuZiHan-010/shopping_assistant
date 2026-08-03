import { expect, test, type ConsoleMessage } from '@playwright/test'

function collectConsoleErrors(messages: string[]) {
  return (message: ConsoleMessage) => {
    if (message.type() === 'error') {
      messages.push(message.text())
    }
  }
}

test('助手入口展示 Borough 主布局且无控制台错误', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Borough 商家 AI 助手' })).toBeVisible()
  await expect(page.getByLabel('输入问题')).toBeVisible()
  await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家100')
  expect(errors).toEqual([])
})

test('知识库占位页可打开且无控制台错误', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))

  await page.goto('/knowledge-base')

  await expect(page.getByRole('heading', { name: '知识库' })).toBeVisible()
  expect(errors).toEqual([])
})

test('未知路径回到助手入口，不存在登录页', async ({ page }) => {
  await page.goto('/login')

  await expect(page).toHaveURL('/')
  await expect(page.getByRole('heading', { name: 'Borough 商家 AI 助手' })).toBeVisible()
})
