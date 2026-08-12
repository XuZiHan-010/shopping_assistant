import { expect, test } from '@playwright/test'

// F3 Task 7：Playwright 强制 VITE_USE_MOCK=true 跑 e2e，Mock 若仍是一张全局
// 会话表，这条隔离断言在 Mock 上永远为真、在真实后端商家隔离被打破时也不会
// 报警——是假绿。Mock 现在按收到的 Authorization 头分租户（同一 origin 下的
// 商家 Token 不同就落进不同的表），这里断言的就是那份分租户行为真的生效。
test('切换商家后看不到上一个商家的会话', async ({ page }) => {
  await page.goto('/')

  // 商家 A（默认选中的 Borough商家100）完成一轮问答。
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('chat-message')).toHaveCount(2)
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  await page.getByLabel('打开对话目录').click()
  await expect(page.getByTestId('conversation-item')).toHaveCount(1)
  await page.getByLabel('关闭历史会话').click()

  // 切到商家 B。
  await page.getByLabel('切换当前演示商家').click()
  await page.locator('[role="option"][data-merchant="Borough商家101"]').click()

  // 商家 B 的抽屉里不该看到商家 A 的会话。
  await page.getByLabel('打开对话目录').click()
  await expect(page.getByTestId('conversation-item')).toHaveCount(0)
})
