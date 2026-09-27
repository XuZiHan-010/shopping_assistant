import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:8014'
const ORDER_ID = '00000000-0000-0000-0000-0000000054c1'

test('S4 商家售后队列、Agent 起草与人工审批后回复可见', async ({ page, request }) => {
  const guest = await request.post(`${API}/api/v2/shop/sessions`, {
    data: { shop_slug: 'borough-s4-e2e' },
  })
  expect(guest.status()).toBe(201)
  const customerHeaders = { 'X-Session-Id': (await guest.json()).session_id as string }
  expect((await request.post(`${API}/api/v2/shop/sessions/demo-customer`, {
    headers: customerHeaders, data: {},
  })).status()).toBe(200)
  const saleRequest = {
    client_request_id: 's4-browser-sale', order_id: ORDER_ID,
    after_sale_type: 'RETURN_REFUND', reason: '商品破损',
  }
  const preview = await request.post(`${API}/api/v2/shop/after-sales`, {
    headers: customerHeaders, data: saleRequest,
  })
  expect(preview.status()).toBe(200)
  const created = await request.post(`${API}/api/v2/shop/after-sales`, {
    headers: customerHeaders,
    data: { ...saleRequest, confirmation_token: (await preview.json()).confirmation_token },
  })
  expect(created.status()).toBe(201)
  const saleId = (await created.json()).id as string

  const merchantSession = await request.post(`${API}/api/v2/merchant/sessions`, {
    headers: { Authorization: 'Bearer s4-e2e-merchant-token' }, data: {},
  })
  expect(merchantSession.status()).toBe(201)
  const merchantHeaders = { 'X-Session-Id': (await merchantSession.json()).session_id as string }
  const chat = await request.post(`${API}/api/v2/merchant/chat`, {
    headers: { ...merchantHeaders, Accept: 'application/json' },
    data: { client_request_id: 's4-browser-draft', message: `请查看本店售后并为 ${saleId} 起草同意决定` },
  })
  expect(chat.status()).toBe(200)
  const drafts = await request.get(`${API}/api/v2/merchant/drafts`, { headers: merchantHeaders })
  expect(drafts.status()).toBe(200)
  const draftId = ((await drafts.json()).items as { id: string }[])[0]?.id
  expect(draftId).toBeTruthy()

  await page.goto('/after-sales')
  await expect(page.getByRole('heading', { name: '售后队列' })).toBeVisible()
  await page.getByRole('button', { name: /退货退款.*(Buyer|顾客)/ }).click()
  await expect(page.getByText('商品破损')).toBeVisible()
  await page.goto(`/approvals/${draftId}`)
  await expect(page.locator('[data-test=diff-row]')).toHaveCount(2)
  await expect(page.getByText('已受理，请按售后详情继续操作。')).toBeVisible()
  await page.locator('[data-test=approve]').click()
  await expect(page.getByText('已批准并应用。')).toBeVisible()
  await page.goto('/after-sales')
  await page.getByRole('button', { name: /退货退款.*(Buyer|顾客)/ }).click()
  await expect(page.getByText('已受理，请按售后详情继续操作。')).toBeVisible()
  await page.goto('/customer-signals')
  await expect(page.getByRole('heading', { name: '顾客信号' })).toBeVisible()
  await expect(page.getByText('退货申请')).toBeVisible()
})
