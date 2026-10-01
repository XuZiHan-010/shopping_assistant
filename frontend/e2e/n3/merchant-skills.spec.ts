/** N3 商家工作台浏览器验收：真实 PostgreSQL/API + 脚本化 Fake LLM。 */
import { expect, test, type Page } from '@playwright/test'

const API = 'http://127.0.0.1:8014'
const SHOP = 'borough-s3-e2e'

/**
 * 首页简报卡「去审批（N）」→ 审批列表里按标题找到那份草稿 → 进入审批详情。
 * W Task 8 之前这一步在 `/today` 的待批准草稿列表里完成（断言不变：草稿可见、点进审批页）。
 */
async function openPendingDraft(page: Page, title: string) {
  await page.goto('/')
  await page.getByRole('link', { name: /^去审批（\d+\+?）$/ }).click()
  await expect(page).toHaveURL(/\/approvals$/)
  const draft = page.getByRole('main').getByRole('listitem').filter({ hasText: title })
  await expect(draft).toBeVisible()
  await draft.getByRole('link', { name: '查看详情' }).click()
}

async function ask(page: Page, question: string, answer: RegExp) {
  await page.goto('/ops-assistant')
  await page.getByRole('textbox', { name: '向运营助手提问' }).fill(question)
  const send = page.getByRole('button', { name: '发送' })
  await send.click()
  await expect(page.locator('.ops-view__bubble').last()).toContainText(answer)
  await expect(page.getByRole('textbox', { name: '向运营助手提问' })).toBeEnabled({ timeout: 30_000 })
}

test('S2：顾客问缺失产地 → 商家收到信号并审批补齐 → 顾客可获回答', async ({ page, context }) => {
  await page.goto('/inventory')
  await expect(page.getByRole('heading', { name: '商品内容与库存' })).toBeVisible()
  const card = page.locator('.inventory-view__cards li').filter({ hasText: 'N3 滞销商品' })
  await expect(card).toBeVisible()
  await expect(card).toContainText('待补属性')
  await expect(card).toContainText('产地')

  const shop = await context.newPage()
  await shop.goto('http://127.0.0.1:3275/borough-s3-e2e')
  await expect(shop.getByRole('navigation', { name: '店铺视图' }).getByRole('link', { name: '智能助手' })).toHaveAttribute('aria-current', 'page')
  await expect(shop).toHaveURL(/\/borough-s3-e2e$/)
  await expect(shop.getByText('购物车还是空的。')).toBeVisible() // 等待顾客会话创建及客户端水合
  const question = 'N3 滞销商品的产地是哪里？'
  async function askOrigin(expected: string) {
    await shop.getByRole('textbox', { name: '向智能助手提问' }).fill(question)
    await shop.getByRole('button', { name: '发送' }).click()
    await expect(shop.locator('[aria-live="polite"] > li').last()).toContainText(expected)
  }
  await askOrigin('商家尚未提供产地')
  await page.goto('/customer-signals')
  await expect(page.locator('.signals-view__list li').filter({ hasText: 'N3 滞销商品' })).toContainText('内容缺口')

  await ask(page, '给商品补上产地', /审批页核对/)
  // W Task 8：今日简报并入首页，待批准草稿从简报卡的「去审批（N）」进入审批列表。
  await openPendingDraft(page, 'N3 滞销商品')
  await page.locator('[data-test=approve]').click()
  await expect(page.getByText('已批准并应用。')).toBeVisible()
  await askOrigin('产地是浙江')
  await shop.close()
})

test('S5：本周成交分析显示归因回答和后端图表', async ({ page }) => {
  await ask(page, '为什么本周成交下滑？', /类目归因/)
  await expect(page.getByRole('region', { name: '指标图表' })).toBeVisible()
  await expect(page.locator('.chart-panel__figure')).toBeVisible()
  await expect(page.locator('.ops-view__log')).toContainText('时间吻合只是线索')
})

test('S6：滞销告警 → 起草折扣券 → 审批后顾客端可见', async ({ page }) => {
  const customerCoupons = async () => {
    const response = await fetch(`${API}/api/v2/shop/stores/${SHOP}/coupons`)
    expect(response.status).toBe(200)
    return (await response.json()) as { items: { name: string; discount_bps: number }[] }
  }
  await page.goto('/inventory')
  await expect(page.getByRole('row', { name: /N3 滞销商品/ })).toBeVisible()
  expect((await customerCoupons()).items.some((item) => item.name === 'N3 九折券')).toBe(false)

  await ask(page, '给滞销商品起草九折券', /审批页核对/)
  expect((await customerCoupons()).items.some((item) => item.name === 'N3 九折券')).toBe(false)
  await openPendingDraft(page, 'N3 九折券')
  await expect(page.getByText('应用时将按当时生效的配置重新检查')).toBeVisible()
  await page.locator('[data-test=approve]').click()
  await expect(page.getByText('已批准并应用。')).toBeVisible()
  await expect.poll(async () => (await customerCoupons()).items.find((item) => item.name === 'N3 九折券')?.discount_bps).toBe(9000)
  await page.goto('/inventory')
  const couponCard = page.locator('.inventory-view__cards li').filter({ hasText: 'N3 九折券' })
  await expect(couponCard).toContainText('生效中')
  await expect(couponCard).toContainText('优惠 10%')
})

test('S7：同一回合展示正式口径与规则来源', async ({ page }) => {
  await ask(page, '净成交额怎么算，退货运费谁出？', /净成交额等于/)
  await expect(page.locator('.ops-view__log')).toContainText('平台规则/after_sale_freight.md')
})
