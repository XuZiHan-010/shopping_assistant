/** WS 顾客店面验收：真实 API / PostgreSQL，聊天只走脚本化 Fake LLM。 */
import { expect, test, type Page } from '@playwright/test'

const SHOP = '/borough-s1-e2e'

async function noHorizontalOverflow(page: Page) {
  const width = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: innerWidth }))
  expect(width.page).toBeLessThanOrEqual(width.viewport)
}

async function bind(page: Page) {
  await page.getByRole('button', { name: '访客' }).click()
  await page.getByRole('group', { name: '访客' }).getByRole('button', { name: '绑定演示顾客' }).click()
  await expect(page.getByTestId('identity')).toHaveText('演示顾客')
}

test('访客首页不查订单，快捷提问进入对话', async ({ page }) => {
  const orderRequests: string[] = []
  page.on('request', request => {
    if (/\/api\/v2\/shop\/orders(?:\/|\?)/.test(request.url())) orderRequests.push(request.url())
  })
  await page.goto(SHOP)
  await expect(page.getByText('绑定演示顾客后，这里会显示你最近的订单和物流。')).toBeVisible()
  await expect(page.getByText('购物车还是空的。')).toBeVisible() // 等待会话与客户端交互就绪
  await expect(page.getByRole('heading', { name: '本周热门' })).toBeVisible()
  expect(orderRequests).toEqual([])
  await page.getByRole('button', { name: /通勤穿的皮鞋/ }).click()
  await expect(page.getByRole('heading', { name: '和智能助手的对话' })).toBeVisible()
  await expect(page.locator('[aria-live="polite"] > li').first()).toContainText('通勤穿的皮鞋')
})

test('绑定后首页出现待付款订单，问问调用只读订单工具', async ({ page }) => {
  await page.goto(SHOP)
  await bind(page)
  await page.getByRole('button', { name: /羊绒围巾/ }).click()
  const sheet = page.getByRole('dialog', { name: '羊绒围巾' })
  await sheet.getByRole('button', { name: '加入购物车' }).click()
  await expect(sheet.getByText('已加入购物车')).toBeVisible()
  await sheet.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('complementary', { name: '购物车' }).getByRole('button', { name: '提交订单' }).click()
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('main')).toHaveCount(1)
  const orderId = page.url().split('/').at(-1)!
  await page.getByRole('navigation', { name: '店铺视图' }).getByRole('link', { name: '智能助手' }).click()
  await expect(page.getByRole('heading', { name: '进行中的订单' })).toBeVisible()
  const row = page.getByRole('region', { name: '进行中的订单' }).getByRole('listitem').filter({ hasText: '待付款' }).first()
  await expect(row).toContainText('待付款')
  await row.getByRole('button', { name: '去支付' }).click()
  await expect(page).toHaveURL(new RegExp(`/orders/${orderId}$`))
  await page.locator('.ws-order').filter({ hasText: orderId }).getByRole('button', { name: '去支付' }).click()
  await expect(page.getByText('已支付').first()).toBeVisible()
  await page.getByRole('navigation', { name: '店铺视图' }).getByRole('link', { name: '智能助手' }).click()
  await page.getByRole('region', { name: '进行中的订单' }).getByRole('button', { name: '问问' }).first().click()
  await expect(page.locator('[aria-live="polite"] > li').last()).toContainText('这笔订单当前状态')
  await page.getByRole('button', { name: /查了 \d+ 步/ }).click()
  await expect(page.getByText('查询订单')).toBeVisible()
})

test('语言切换后界面、商品和回答使用英文', async ({ page }) => {
  await page.goto(SHOP)
  await expect(page.getByText('购物车还是空的。')).toBeVisible()
  await page.getByRole('button', { name: '偏好设置' }).click()
  await expect(page.getByRole('dialog', { name: '偏好设置' })).toBeVisible()
  await page.getByRole('dialog', { name: '偏好设置' }).getByRole('button', { name: '浅色' }).click()
  await expect.poll(() => page.locator('body').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(246, 241, 231)')
  await expect.poll(() => page.locator('.shop-tabs a[aria-current="page"]').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(31, 59, 47)')
  await page.getByRole('dialog', { name: '偏好设置' }).getByRole('button', { name: '深色' }).click()
  await expect.poll(() => page.locator('body').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(19, 24, 22)')
  await page.getByRole('dialog', { name: '偏好设置' }).getByRole('button', { name: '大', exact: true }).click()
  await expect.poll(() => page.locator('html').evaluate(element => getComputedStyle(element).fontSize)).toBe('17.6px')
  await page.getByRole('dialog', { name: '偏好设置' }).getByRole('button', { name: 'English' }).click()
  await page.reload()
  await expect.poll(() => page.locator('body').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(19, 24, 22)')
  await expect.poll(() => page.locator('html').evaluate(element => getComputedStyle(element).fontSize)).toBe('17.6px')
  await expect(page.getByRole('navigation', { name: 'Store views' }).getByRole('link', { name: 'Assistant' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Cashmere scarf/ })).toBeVisible()
  await page.getByRole('textbox', { name: 'Ask the assistant' }).fill('Hello')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('[aria-live="polite"] > li').last()).toContainText('Hello, I can help')
  await page.setViewportSize({ width: 375, height: 812 })
  await noHorizontalOverflow(page)
})

test('旧路由重定向，375px 下抽屉和偏好面板无横向滚动', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto(`${SHOP}/assistant`)
  await expect(page).toHaveURL(new RegExp(`${SHOP}$`))
  await noHorizontalOverflow(page)
  await expect(page.getByRole('button', { name: '偏好设置' })).toBeVisible()
  await expect.poll(async () => (await page.getByRole('button', { name: '偏好设置' }).boundingBox())?.y ?? 0).toBeGreaterThan(680) // 左下角，不占顶栏空间
  await page.goto(`${SHOP}/cart`)
  await expect(page).toHaveURL(new RegExp(`${SHOP}$`))
  await expect(page.getByRole('complementary', { name: '购物车' })).toBeVisible()
  await noHorizontalOverflow(page)
  await page.goto(`${SHOP}/memories`)
  await expect(page).toHaveURL(new RegExp(`${SHOP}$`))
  await expect(page.getByRole('dialog', { name: '动态' }).getByRole('tab', { name: '我记住的' })).toHaveAttribute('aria-selected', 'true')
  await noHorizontalOverflow(page)
  await page.getByRole('dialog', { name: '动态' }).getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '偏好设置' }).click()
  await noHorizontalOverflow(page)
  await page.getByRole('dialog', { name: '偏好设置' }).getByRole('button', { name: '关闭' }).click()
  await bind(page)
  await page.getByRole('button', { name: /羊绒围巾/ }).click()
  const sheet = page.getByRole('dialog', { name: '羊绒围巾' })
  await sheet.getByRole('button', { name: '加入购物车' }).click()
  await expect(sheet.getByText('已加入购物车')).toBeVisible()
  await sheet.getByRole('button', { name: '关闭' }).click()
  await page.getByRole('button', { name: '购物车' }).click()
  await expect(page.locator('.shop-app')).toHaveAttribute('data-panel', 'cart')
  await page.getByRole('complementary', { name: '购物车' }).getByRole('button', { name: '提交订单' }).click()
  await expect(page).toHaveURL(/\/orders\/[0-9a-f-]{36}$/)
  await expect(page.locator('.shop-app')).toHaveAttribute('data-panel', 'closed')
  await noHorizontalOverflow(page)
})
