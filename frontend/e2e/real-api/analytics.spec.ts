import { expect, test } from '@playwright/test'

test('真实后端 SSE 返回的 PostgreSQL GMV 数据会渲染图表', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('输入问题')).toBeVisible()

  await page.getByLabel('输入问题').fill('查看 GMV 趋势')
  await page.getByLabel('发送问题').click()

  await expect(page.getByText('成交 GMV 趋势')).toBeVisible()
  await expect(page.getByTestId('chart-summary')).toContainText('360.5')
  await expect(page.getByTestId('chart-empty')).toHaveCount(0)
})

test('真实后端返回的订单明细渲染表格与带签名的下载链接', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('输入问题')).toBeVisible()

  await page.getByLabel('输入问题').fill('查看订单明细')
  await page.getByLabel('发送问题').click()

  const table = page.getByTestId('detail-table')
  await expect(table).toBeVisible()
  await expect(table).toContainText('共 2 行')
  await expect(table).toContainText('F4-E2E-001')
  await expect(table).toContainText('F4-E2E-002')

  const download = page.getByTestId('download-export')
  await expect(download).toBeVisible()
  const href = await download.getAttribute('href')
  // 签名由真实 ExportService 在这次请求里现算，不是固定 Fixture 值——
  // 只能断言形状，不能断言具体的 signature 取值。
  expect(href).toMatch(
    /^http:\/\/127\.0\.0\.1:8011\/api\/exports\/.+\?merchant_id=[0-9a-f-]+&expires_at=\d+&signature=[0-9a-f]{64}$/,
  )
})

test('切换商家后看不到另一个商家的经营数据', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('查看 GMV 趋势')
  await page.getByLabel('发送问题').click()
  await expect(page.getByTestId('chart-summary')).toContainText('360.5')

  await page.getByLabel('切换当前演示商家').click()
  await page.locator('[role="option"][data-merchant="Borough商家101"]').click()
  await expect(page.getByTestId('chat-message')).toHaveCount(0)

  await page.getByLabel('输入问题').fill('查看 GMV 趋势')
  await page.getByLabel('发送问题').click()

  // 商家 B 只有一笔 999.99 的订单：既要看到自己的数据，也不能看到商家 A 的总额。
  await expect(page.getByTestId('chart-summary')).toContainText('999.99')
  await expect(page.getByTestId('chart-summary')).not.toContainText('360.5')

  await page.getByLabel('输入问题').fill('查看订单明细')
  await page.getByLabel('发送问题').click()
  const table = page.getByTestId('detail-table')
  await expect(table).toBeVisible()
  await expect(table).toContainText('F4-E2E-B01')
  await expect(table).not.toContainText('F4-E2E-001')
  await expect(table).not.toContainText('F4-E2E-002')
})

test('纯明细只渲染表格，分析型明细保留正文与建议', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('查看最近 20 笔订单')
  await page.getByLabel('发送问题').click()

  await expect(page.getByTestId('detail-table')).toBeVisible()
  await expect(page.locator('.chat-message--assistant .chat-message__text')).toHaveCount(0)

  await page.getByLabel('输入问题').fill('分析最近 20 笔订单')
  await page.getByLabel('发送问题').click()

  await expect(page.getByTestId('select-round').last()).toContainText('已查询真实演示数据')
  await expect(page.getByText('核对订单状态')).toBeVisible()
})

test('跨业务订单查询不会泄露另一商家的关联记录', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('查询订单 F4-E2E-001 的退款')
  await page.getByLabel('发送问题').click()
  await expect(page.getByTestId('detail-table')).toContainText('F4-E2E-001')
  await expect(page.getByTestId('detail-table')).toContainText('12.5')

  await page.getByLabel('输入问题').fill('查询订单 F4-E2E-B01 的退款')
  await page.getByLabel('发送问题').click()
  const fallbackTable = page.getByTestId('detail-table').last()
  await expect(fallbackTable).toBeVisible()
  await expect(fallbackTable).not.toContainText('F4-E2E-B01')
  await expect(fallbackTable).not.toContainText('99.99')
})

test('生成指标展示待核验口径和安全图表', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('按城市查看临时成交指标')
  await page.getByLabel('发送问题').click()

  await expect(page.getByTestId('metric-chart-canvas')).toBeVisible()
  await expect(page.getByTestId('metric-unverified')).toBeVisible()
  await expect(page.getByTestId('metric-unverified')).toContainText('仍需人工确认')
  await expect(page.getByText('待核验')).toBeVisible()
})

test('被截断的生成指标提供签名 CSV 下载链接', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('按商品查看临时成交指标')
  await page.getByLabel('发送问题').click()

  await expect(page.getByTestId('detail-table')).toContainText('已展示前 200 行')
  const href = await page.getByTestId('download-export').getAttribute('href')
  expect(href).toMatch(
    /^http:\/\/127\.0\.0\.1:8011\/api\/exports\/.+\?merchant_id=[0-9a-f-]+&expires_at=\d+&signature=[0-9a-f]{64}$/,
  )
})

test('历史会话重放完整步骤且不暴露签名 URL', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('输入问题').fill('查看 GMV 趋势')
  await page.getByLabel('发送问题').click()
  await expect(page.getByTestId('thinking-step')).toContainText('查询真实经营数据')

  await page.reload()
  await page.getByLabel('打开对话目录').click()
  await page.getByTestId('conversation-open').first().click()
  await expect(page.getByTestId('thinking-step')).toContainText('查询真实经营数据')
  await expect(page.locator('body')).not.toContainText('signature=')
})
