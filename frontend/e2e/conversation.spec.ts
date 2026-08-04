import { expect, test } from '@playwright/test'

test('点击快速问题可完成一轮问答，阶段标签先于回答出现', async ({ page }) => {
  await page.goto('/')

  const quick = page.getByTestId('quick-question').first()
  // 按钮文案含分类眉标，取 data-question 才是问题本身。
  const question = await quick.getAttribute('data-question')
  await quick.click()

  await expect(page.getByTestId('stage-label')).toBeVisible({ timeout: 1000 })
  await expect(page.getByTestId('chat-message').first()).toContainText(question!)
  await expect(page.getByTestId('chat-message')).toHaveCount(2)
})

test('连续两轮后目录含两个节点，点击可切换侧栏内容', async ({ page }) => {
  await page.goto('/')
  // 第一个入口是「趋势分析 · 最近7天退货量趋势」，METRIC 模式。
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('chat-message')).toHaveCount(2)
  // 必须等第一轮跑完：并发提交现在会被封住，输入区在流式期间是禁用的。
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  await page.getByLabel('输入问题').fill('我要货品上架，具体规则有吗？')
  await page.getByLabel('发送问题').click()
  await expect(page.getByTestId('chat-message')).toHaveCount(4)
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  await expect(page.getByTestId('conversation-nav-item')).toHaveCount(2)
  await page.getByTestId('conversation-nav-item').first().click()
  await expect(page.getByTestId('metric-empty')).toBeHidden()
})

test('切换商家清空会话与侧栏', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('chat-message')).toHaveCount(2)

  await page.getByLabel('切换当前演示商家').click()
  await page.locator('[role="option"][data-merchant="Borough商家101"]').click()

  await expect(page.getByTestId('chat-message')).toHaveCount(0)
  await expect(page.getByTestId('quick-question').first()).toBeVisible()
})

test('刷新后选回同一商家', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('切换当前演示商家').click()
  await page.locator('[role="option"][data-merchant="Borough商家102"]').click()

  await page.reload()

  await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家102')
})

test('停止按钮真正中断本轮，且文案不说「出错」', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('最近7天退货量趋势')
  await page.getByLabel('发送问题').click()

  await page.getByTestId('cancel-button').click()

  await expect(page.getByTestId('chat-message').nth(1)).toContainText('已取消')
  await expect(page.getByTestId('chat-message').nth(1)).not.toContainText('出错')
  await expect(page.getByTestId('stage-label')).toHaveCount(0)
})

test('跨 560px 断点调整窗口后选中商家不丢失', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 })
  await page.goto('/')
  await page.getByLabel('切换当前演示商家').click()
  await page.locator('[role="option"][data-merchant="Borough商家101"]').click()

  await page.setViewportSize({ width: 420, height: 900 })
  await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家101')

  await page.setViewportSize({ width: 900, height: 900 })
  await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家101')
})

test('删除会话后列表同步移除', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('chat-message')).toHaveCount(2)

  await page.getByLabel('打开对话目录').click()
  await expect(page.getByTestId('conversation-item')).toHaveCount(1)

  // 删除不可撤销，所以要两步：第一步进确认态，会话仍在。
  await page.getByTestId('conversation-delete').first().click()
  await expect(page.getByTestId('conversation-item')).toHaveCount(1)

  await page.getByTestId('conversation-delete-confirm').first().click()
  await expect(page.getByTestId('conversation-item')).toHaveCount(0)
})

test('演示数据在回答卡片上有明确标识（R7）', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  const notice = page.getByTestId('degraded-notice')
  await expect(notice).toBeVisible()
  await expect(notice).toContainText('演示数据')
  await expect(notice).toContainText('FALLBACK')
})

test('桌面宽度下商家名完整可见，不被截断', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家100')

  // 三个演示商家只差最后一位数字，截断就等于无法确认当前身份。
  const truncated = await page
    .locator('.merchant-switcher__name')
    .evaluate((el) => el.scrollWidth > el.clientWidth)
  expect(truncated).toBe(false)
})
