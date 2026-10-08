/**
 * 单入口演示在本地 compose 全栈上的冒烟（PRD §10.7，D-N5-4）。
 *
 * 前置条件（都在仓库根目录执行）：
 *   docker compose exec postgres createdb -U borough borough_compose_demo
 *   COMPOSE_DB_NAME=borough_compose_demo docker compose up -d
 *   按 docs/deployment.md「演示前数据检查清单」向该库灌演示商家与经营数据
 *
 * 运行：`npx playwright test --config playwright.compose.config.ts`。
 * backend 没有配置 LLM_API_KEY：助手回答是可见降级，这里只要求它不是报错。
 */
import { expect, test } from '@playwright/test'

const SHOP_URL = process.env.COMPOSE_SHOP_URL ?? 'http://localhost:3000'
const SHOP_SLUG = 'borough-demo-100'

test('从商家端「顾客视角」进入本店顾客端，两端各用自己的会话', async ({ page, context }) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })

  // 商家端：真实镜像 + 真实 backend，首页主指标来自演示数据。
  await page.goto('/')
  await expect(page.locator('[data-test=metric-value]')).toBeVisible()

  const entry = page.getByTestId('customer-view-link')
  await expect(entry).toBeVisible()
  await expect(entry).toHaveAttribute('href', `${SHOP_URL}/${SHOP_SLUG}`)

  const [shop] = await Promise.all([context.waitForEvent('page'), entry.click()])
  await shop.waitForLoadState()

  // 链接里没有任何凭证或查询参数，新标签也拿不到商家端窗口。
  expect(shop.url()).toBe(`${SHOP_URL}/${SHOP_SLUG}`)
  expect(await shop.evaluate(() => window.opener)).toBeNull()

  // 顾客端：访客身份，能看到本店商品（CORS 已放行顾客端 Origin）与六条快捷提问。
  await expect(shop.getByRole('heading', { name: '本周热门' })).toBeVisible()
  await expect(shop.getByText('绑定演示顾客后，这里会显示你最近的订单和物流。')).toBeVisible()
  const quick = shop.getByRole('group', { name: '快捷提问' })
  await expect(quick.getByRole('button')).toHaveCount(6)

  // 点一条快捷提问：进入对话并得到一条助手消息（未配置模型时为可见降级，不是报错）。
  await quick.getByRole('button', { name: /通勤穿的鞋/ }).click()
  await expect(shop.getByRole('heading', { name: '和智能助手的对话' })).toBeVisible()
  const turns = shop.locator('[aria-live="polite"] > li')
  await expect(turns.first()).toContainText('通勤穿的鞋')
  await expect(turns).toHaveCount(2)
  await expect(turns.nth(1)).not.toBeEmpty()

  expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
})
