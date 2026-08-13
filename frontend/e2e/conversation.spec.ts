import { expect, test, type Page } from '@playwright/test'

async function tabToLabel(page: Page, label: string, limit = 60): Promise<void> {
  for (let index = 0; index < limit; index += 1) {
    await page.keyboard.press('Tab')
    const activeLabel = await page.evaluate(() =>
      document.activeElement?.getAttribute('aria-label'),
    )
    if (activeLabel === label) return
  }
  throw new Error(`键盘 Tab ${limit} 次后仍未聚焦「${label}」`)
}

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
  // 用户消息先进入 DOM，回答持久化与会话目录更新仍在流式阶段尾部；必须等该轮结束。
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15_000 })

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
  // 快捷问题现在命中真实（非降级）数据，用会命中 identityProfile 降级夹具的问题触发。
  await page.getByLabel('输入问题').fill('我的商家资料是什么？')
  await page.getByLabel('发送问题').click()
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  const notice = page.getByTestId('degraded-notice')
  await expect(notice).toBeVisible()
  await expect(notice).toContainText('演示数据')
  await expect(notice).toContainText('兜底回答')
  await expect(notice).not.toContainText('FALLBACK')
})

test('METRIC 回答在侧栏渲染图表 canvas 与可键盘访问的数据表', async ({ page }) => {
  await page.goto('/')
  // 第二个快捷问题「昨天总 GMV 是多少？」命中 metric-gmv fixture，图表已启用。
  await page.getByTestId('quick-question').nth(1).click()
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  await expect(page.getByTestId('metric-chart-canvas')).toBeVisible()
  await expect(page.getByTestId('chart-summary')).not.toBeEmpty()
  await expect(page.getByTestId('chart-empty')).toHaveCount(0)

  await page.getByText('查看数据表').click()
  await expect(page.locator('details table th[scope="col"]').first()).toBeVisible()
})

test('RULE 回答不展示虚构图表', async ({ page }) => {
  await page.goto('/')
  // 第四个快捷问题「我要货品上架，具体规则有吗？」命中 rule-platform fixture，无 visualization。
  await page.getByTestId('quick-question').nth(3).click()
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  await expect(page.getByTestId('chart-empty')).toBeVisible()
  await expect(page.locator('[data-testid="metric-chart-canvas"] canvas')).toHaveCount(0)
})

test('DETAIL 回答在消息内渲染表格、行数说明与带签名的下载链接', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-07-28T12:00:00Z') })
  await page.goto('/')
  // 第三个快捷问题「查看最近订单明细」命中 detail-order fixture。
  await page.getByTestId('quick-question').nth(2).click()
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  const table = page.getByTestId('detail-table')
  await expect(table).toBeVisible()
  await expect(table).toContainText('共 2 行')

  const download = page.getByTestId('download-export')
  await expect(download).toBeVisible()
  await expect(download).toHaveAttribute('download', '')
  await expect(download).toHaveAttribute('target', '_blank')
  await expect(download).toHaveAttribute('rel', 'noopener')
  const href = await download.getAttribute('href')
  expect(href).toMatch(
    /\/api\/exports\/.+\?merchant_id=[0-9a-f-]+&expires_at=\d+&signature=[0-9a-f]{64}/,
  )
})

test('换一换只在本地循环备选问题，不触发新的一轮请求', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('quick-question').nth(1).click()
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15000 })

  await expect(page.getByTestId('chat-message')).toHaveCount(2)
  const before = await page.getByTestId('suggested-question').allTextContents()

  await page.getByTestId('rotate-suggestions').click()

  const after = await page.getByTestId('suggested-question').allTextContents()
  expect(after).not.toEqual(before)
  // 本地轮换不产生新的一轮问答，也不应该重新出现阶段标签。
  await expect(page.getByTestId('chat-message')).toHaveCount(2)
  await expect(page.getByTestId('stage-label')).toHaveCount(0)
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

test('键盘可完成提问、阅读回答与采纳反馈', async ({ page }) => {
  await page.goto('/')

  await tabToLabel(page, '输入问题')
  await page.keyboard.type('昨天总 GMV 是多少？')
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByLabel('质量校验轨迹')).toBeVisible()

  await tabToLabel(page, '采纳本轮回答')
  await page.keyboard.press('Enter')

  await expect(page.getByLabel('采纳本轮回答')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('feedback-status')).toHaveText('已记录')
})
