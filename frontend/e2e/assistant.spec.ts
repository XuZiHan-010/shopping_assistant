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

  // 走一整轮流式问答再收口断言：静态首屏本来就不碰 SSE 解析、Adapter 和状态机，
  // 只看首屏的话，流式路径上的报错永远进不了「无控制台错误」的覆盖范围。
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('stage-label')).toBeVisible()
  // Mock 传输层按字节分块并逐块 sleep，整轮耗时随载荷大小线性增长：B3 的问答图把
  // 步骤从 3 个增加到 13 个之后，一轮要 5 秒以上，正好卡在默认断言窗口边界上。
  // 这里显式给出等待上限，而不是依赖默认值——默认值一变，失败原因会指向错误的地方。
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByTestId('chat-message').nth(1)).not.toBeEmpty()

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
