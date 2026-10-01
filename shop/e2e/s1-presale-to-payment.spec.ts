/**
 * 场景 S1 浏览器验收：售前导购到支付（PRD §12.2）。
 *
 * 进入店铺 → 绑定演示顾客 → 向导购提问 → Agent 对比两款商品并加购
 * → 购物车页提交订单 → 订单页模拟支付 → 订单页显示「已支付」。
 *
 * 后端是真实代码 + 真实 PostgreSQL，只有「模型决定调哪个工具」被脚本化（零 LLM 费用）。
 * 页面内导航一律点链接，不用 `page.goto`：会话只存浏览器内存，整页跳转会丢会话（这正是
 * PRD C3 的行为，刷新相关用例专门验证它）。
 */
import { expect, test, type Page } from '@playwright/test'

const SHOP = '/borough-s1-e2e'
const BACKEND = 'http://127.0.0.1:8013'
const QUESTION = '冬天想买条围巾，比较一下再帮我加一条'

function trackSessionIds(page: Page): string[] {
  const seen: string[] = []
  page.on('request', (request) => {
    const id = request.headers()['x-session-id']
    if (id && !seen.includes(id)) seen.push(id)
  })
  return seen
}

async function openShop(page: Page) {
  await page.goto(SHOP)
  await expect(page.getByTestId('identity')).toHaveText('访客')
}

async function bindDemoCustomer(page: Page) {
  await page.getByRole('button', { name: '访客' }).click()
  await page.getByRole('group', { name: '访客' }).getByRole('button', { name: '绑定演示顾客' }).click()
  await expect(page.getByTestId('identity')).toHaveText('演示顾客')
}

async function addCashmereFromProductPage(page: Page) {
  await page.getByRole('button', { name: /羊绒围巾/ }).click()
  const sheet = page.getByRole('dialog', { name: '羊绒围巾' })
  await expect(sheet.getByRole('heading', { name: '羊绒围巾' })).toBeVisible()
  await sheet.getByRole('button', { name: '加入购物车' }).click()
  await expect(page.getByText('已加入购物车')).toBeVisible()
  await sheet.getByRole('button', { name: '关闭' }).click()
}

async function emptyBuyerCart(page: Page) {
  const remove = page.getByRole('complementary', { name: '购物车' }).getByRole('button', { name: '移除' })
  while ((await remove.count()) > 0) {
    await remove.first().click()
    await page.waitForTimeout(150)
  }
}

test.describe.configure({ mode: 'serial' })

test('S1：进入店铺 → 绑定演示顾客 → 导购对比并加购 → 提交订单 → 模拟支付 → 已支付', async ({ page }) => {
  const sessionIds = trackSessionIds(page)

  // 进入店铺：公开页面由服务端渲染，库存只有三档，没有数量。
  await openShop(page)
  await expect(page.getByRole('heading', { name: '本周热门' })).toBeVisible()
  await expect(page.getByRole('button', { name: /羊毛围巾/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /羊绒围巾/ })).toBeVisible()
  await expect(page.getByRole('region', { name: '本周热门' }).getByText(/仅剩\s*\d+\s*件/)).toHaveCount(0)

  // 选择演示顾客（原地绑定，界面标注演示身份）。
  await bindDemoCustomer(page)
  await expect(page.getByText(/演示环境：身份为演示身份，非真实登录/)).toBeVisible()

  // 向导购提问：Agent 检索、逐个看详情、加购；工具行只有名称与状态。
  await page.getByRole('textbox', { name: '向智能助手提问' }).fill(QUESTION)
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText(/羊绒款是 100% 羊绒/)).toBeVisible()
  await expect(page.getByRole('button', { name: /查了 \d+ 步/ })).toBeVisible()

  // 购物车角标来自服务端 GET /cart。
  const rail = page.getByRole('complementary', { name: '购物车' })
  await expect(rail.getByText('羊绒围巾')).toBeVisible()
  await expect(rail.getByText(/优惠与应付金额以提交订单后系统计算的结果为准/)).toBeVisible()

  // 购物车页：金额来自后端；提交订单，不可用项为空时进入订单页。
  await expect(rail.getByText('¥259.00').first()).toBeVisible()
  await expect(rail.getByText('演示结账，不产生真实扣款。')).toBeVisible()
  await rail.getByRole('button', { name: '提交订单' }).click()

  // 订单页：待支付，常驻演示支付提示；三个状态分开展示。
  await expect(page.getByRole('heading', { name: '我的订单' })).toBeVisible()
  expect(page.url()).toMatch(/\/orders\/[0-9a-f-]{36}$/)
  await expect(page.getByText('待付款').first()).toBeVisible()
  await expect(page.getByText(/演示支付，不产生真实扣款/)).toBeVisible()
  await expect(page.getByText('已下单')).toBeVisible()

  // 模拟支付 → 已支付，事件出现「已支付」，支付按钮消失。
  await page.getByRole('button', { name: '去支付' }).click()
  await expect(page.getByText('已支付').first()).toBeVisible()
  await expect(page.getByRole('listitem').filter({ hasText: '已支付' })).toBeVisible()
  await expect(page.getByRole('button', { name: '去支付' })).toHaveCount(0)

  // 会话 ID 只在请求头里：不在 URL，也不落浏览器持久化存储。
  expect(sessionIds.length).toBeGreaterThan(0)
  for (const id of sessionIds) expect(page.url()).not.toContain(id)
  const storage = await page.evaluate(() =>
    JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + document.cookie,
  )
  for (const id of sessionIds) expect(storage).not.toContain(id)
})

test('刷新①：未绑定访客加购 → 刷新后购物车为空并提示无法找回，但服务端原记录仍在', async ({ page, request }) => {
  const sessionIds = trackSessionIds(page)
  await openShop(page)
  await addCashmereFromProductPage(page)
  // 桌面宽度下购物车是常驻右栏，切换按钮只在窄屏出现。
  const rail = page.getByRole('complementary', { name: '购物车' })
  await expect(rail.getByText('羊绒围巾').first()).toBeVisible()
  await expect(page.getByText(/未绑定身份时刷新后无法找回购物车/)).toBeVisible()
  const originalSession = sessionIds.at(-1)!

  await page.reload()

  // 新访客会话：页面显示空购物车，且明示「无法找回」，不说「已删除」。
  await expect(page.getByText(/购物车还是空的/)).toBeVisible()
  await expect(page.getByText(/未绑定身份时刷新后无法找回购物车/)).toBeVisible()
  await expect(page.getByText(/绑定演示身份后可恢复/)).toBeVisible()
  await expect(page.getByText(/已删除|已清空/)).toHaveCount(0)

  // 服务端原购物车记录仍然存在——证明是「暂时无法访问」，不是被删除。
  const original = await request.get(`${BACKEND}/api/v2/shop/cart`, {
    headers: { 'X-Session-Id': originalSession },
  })
  expect(original.status()).toBe(200)
  const body = (await original.json()) as { items: { name: string; quantity: number }[] }
  expect(body.items.map((item) => item.name)).toEqual(['羊绒围巾'])
})

test('刷新②：已绑定演示顾客加购 → 刷新 → 重新绑定同一身份 → 原购物车商品恢复', async ({ page }) => {
  await openShop(page)
  await bindDemoCustomer(page)
  await addCashmereFromProductPage(page)
  await expect(page.getByRole('complementary', { name: '购物车' }).getByText('羊绒围巾').first()).toBeVisible()

  await page.reload()

  // 刷新后是新的访客会话：购物车暂时看不到。
  await expect(page.getByTestId('identity')).toHaveText('访客')
  await expect(page.getByText(/购物车还是空的/)).toBeVisible()

  // 重新绑定同一演示身份 → 服务端按 buyer_key 返回自己的购物车。
  await bindDemoCustomer(page)
  await expect(page.getByText('羊绒围巾').first()).toBeVisible()
  await expect(page.getByRole('complementary', { name: '购物车' }).getByRole('listitem').filter({ hasText: '羊绒围巾' })).toHaveCount(1)

  await emptyBuyerCart(page)
  await expect(page.getByText(/购物车还是空的/)).toBeVisible()
})

test('访客直达订单 URL 只显示绑定提示，订单接口对存在与不存在的目标同样拒绝', async ({ page, request }) => {
  // 用 API 以演示顾客身份建一笔订单（页面外的第三方持有者）。
  const created = await request.post(`${BACKEND}/api/v2/shop/sessions`, { data: { shop_slug: 'borough-s1-e2e' } })
  const headers = { 'X-Session-Id': ((await created.json()) as { session_id: string }).session_id }
  expect((await request.post(`${BACKEND}/api/v2/shop/sessions/demo-customer`, { headers, data: {} })).status()).toBe(200)
  expect(
    (await request.put(`${BACKEND}/api/v2/shop/cart/items/00000000-0000-0000-0000-0000000051b2`, { headers, data: { quantity: 1 } })).status(),
  ).toBe(200)
  const placed = await request.post(`${BACKEND}/api/v2/shop/orders`, { headers, data: { client_request_id: 'e2e-foreign-order' } })
  expect(placed.status()).toBe(201)
  const foreignOrderId = ((await placed.json()) as { id: string }).id

  // 未绑定访客直达时先展示绑定提示，不发订单请求（WS 的页面入口规则）。
  const orderRequests: string[] = []
  page.on('request', incoming => {
    if (/\/api\/v2\/shop\/orders(?:\/|\?)/.test(incoming.url())) orderRequests.push(incoming.url())
  })
  const sessionIds = trackSessionIds(page)
  await page.goto(`${SHOP}/orders/${foreignOrderId}`)
  await expect(page.getByText('绑定演示顾客后，这里会显示你最近的订单和物流。')).toBeVisible()
  const foreign = await page.locator('#shop-main').innerText()

  // 一个根本不存在的订单：公开页面内容逐字一致，也不查询对象是否存在。
  await page.goto(`${SHOP}/orders/00000000-0000-0000-0000-000000000000`)
  await expect(page.getByText('绑定演示顾客后，这里会显示你最近的订单和物流。')).toBeVisible()
  expect(await page.locator('#shop-main').innerText()).toBe(foreign)
  expect(orderRequests).toEqual([])
  await expect(page.getByText('羊绒围巾')).toHaveCount(0)

  // 服务端仍独立执行同形状的 R5 拒绝，页面不借状态码探测对象存在性。
  expect(sessionIds.length).toBeGreaterThan(0)
  const guestHeaders = { 'X-Session-Id': sessionIds.at(-1)! }
  const [existing, absent] = await Promise.all([
    request.get(`${BACKEND}/api/v2/shop/orders/${foreignOrderId}`, { headers: guestHeaders }),
    request.get(`${BACKEND}/api/v2/shop/orders/00000000-0000-0000-0000-000000000000`, { headers: guestHeaders }),
  ])
  expect(existing.status()).toBe(403)
  expect(absent.status()).toBe(403)
  const existingPublic = await existing.json() as Record<string, unknown>
  const absentPublic = await absent.json() as Record<string, unknown>
  delete existingPublic.request_id
  delete absentPublic.request_id
  expect(existingPublic).toEqual(absentPublic)
})
