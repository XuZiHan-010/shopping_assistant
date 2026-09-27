/**
 * S3 库存闭环浏览器验收（`n2-merchant-vue-v2-migration` Task 7）。
 *
 * 真实后端 + 真实 PostgreSQL + 脚本化模型（零 LLM 费用），种子见
 * `backend/scripts/seed_s3_e2e.py`：「S3 验收商品」在库 3、阈值 5 → `LOW_STOCK`。
 *
 * **对话这一步不走浏览器界面**：本用例写成时 Vue 端还没有 v2 对话界面（2026-09-24 起有了
 * `/ops-assistant`，其浏览器流程见同目录 `ops-assistant-responsive.spec.ts`）。这里由测试进程直接调用真实的
 * `POST /api/v2/merchant/chat`，并用**生产代码** `readMerchantChatStream` 解析真实
 * SSE——既让草稿真的由 Agent 工具起草，也让 Task 6 的适配层在真实服务器上被验证。
 * 同一商家换取的是另一枚会话，草稿对浏览器里的会话同样可见。
 *
 * 顾客侧只经**公开**商品接口（`n2-trade-closed-loop` Task 1）核对档位，不直接查库：
 * 顾客看到的是三档，不是数量（D5）。
 */
import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

import { readMerchantChatStream, type MerchantChatStreamEvent } from '../../src/api/adapters/chatV2'

const API = 'http://127.0.0.1:8012'
const MERCHANT_TOKEN = 's3-e2e-merchant-token'
const PRODUCT = 'S3 验收商品'
const SHOP_SLUG = 'borough-s3-e2e'
const PRODUCT_ID = '00000000-0000-0000-0000-0000000053b1'

/** 顾客公开接口里的库存档位；同时确认响应里没有任何库存数量字段。 */
async function customerStockBand(): Promise<string> {
  const response = await fetch(`${API}/api/v2/shop/stores/${SHOP_SLUG}/products/${PRODUCT_ID}`)
  expect(response.status).toBe(200)
  const raw = await response.text()
  expect(raw).not.toMatch(/stock_on_hand|stock_reserved|stock_available|threshold/)
  return (JSON.parse(raw) as { stock_band: string }).stock_band
}

async function openApiSession(): Promise<string> {
  const response = await fetch(`${API}/api/v2/merchant/sessions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${MERCHANT_TOKEN}`, 'Content-Type': 'application/json' },
    body: '{}',
  })
  expect(response.status).toBe(201)
  return ((await response.json()) as { session_id: string }).session_id
}

async function chat(
  sessionId: string,
  message: string,
  clientRequestId: string,
): Promise<MerchantChatStreamEvent[]> {
  const response = await fetch(`${API}/api/v2/merchant/chat`, {
    method: 'POST',
    headers: {
      'X-Session-Id': sessionId,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ client_request_id: clientRequestId, message }),
  })
  expect(response.status).toBe(200)
  expect(response.headers.get('content-type')).toContain('text/event-stream')
  const events: MerchantChatStreamEvent[] = []
  for await (const event of readMerchantChatStream(response.body!)) events.push(event)
  return events
}

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test('S3：简报出现低库存 → 对话起草补货 → 聊天里「批准」无效 → 审批页核对并批准 → 告警消失、顾客端恢复有货', async ({
  page,
}) => {
  const errors = trackConsoleErrors(page)

  // 0. 顾客端起点：紧张（在库 3 ≤ 阈值 5）。
  expect(await customerStockBand()).toBe('LOW_STOCK')

  // 1. 今日简报：确定性来源、低库存条目、暂无待批准草稿。
  await page.goto('/today')
  await expect(page.getByRole('heading', { name: '今日简报' })).toBeVisible()
  await expect(page.getByText(`库存偏低：${PRODUCT}`)).toBeVisible()
  await expect(page.getByText('暂无待批准草稿。')).toBeVisible()
  await expect(page.locator('body')).not.toContainText(/AI\s*分析/)

  // 2. 对话里让 Agent 起草补货（真实后端 SSE + 生产解析器）。
  const sessionId = await openApiSession()
  const drafted = await chat(sessionId, `给「${PRODUCT}」起草补货`, 's3-e2e-draft')
  const calls = drafted.flatMap((event) =>
    event.type === 'tool_call' ? [event.call.toolName] : [],
  )
  expect(calls).toEqual(['get_inventory_alerts', 'draft_restock'])
  const results = drafted.flatMap((event) => (event.type === 'tool_result' ? [event.result] : []))
  expect(results).toHaveLength(2)
  expect(results.every((result) => result.status === 'SUCCEEDED')).toBe(true)
  const finished = drafted.at(-1)
  expect(finished?.type).toBe('turn_complete')
  expect(finished?.type === 'turn_complete' && finished.envelope.degraded).toBe(false)

  // 3. 反例：聊天里说「批准」，模型也口头声称已批准——不得产生任何效果（D9①）。
  const claimed = await chat(sessionId, '批准那个补货', 's3-e2e-claim-approval')
  expect(claimed.some((event) => event.type === 'tool_call')).toBe(false)
  expect(claimed.at(-1)?.type).toBe('turn_complete')

  // 草稿仍是暂存、库存未变：告警还在，顾客端也仍是紧张。
  await page.goto('/inventory')
  await expect(page.getByRole('row', { name: new RegExp(PRODUCT) })).toBeVisible()
  expect(await customerStockBand()).toBe('LOW_STOCK')

  // 4. 今日页出现待批准草稿 → 进入审批页核对 diff。
  await page.goto('/today')
  const pending = page.locator('.today-view__pending-drafts li')
  await expect(pending).toHaveCount(1)
  await pending.getByRole('link', { name: '去审批' }).click()
  await expect(page).toHaveURL(/\/approvals\/[^/]+$/)

  await expect(page.locator('[data-test=diff-row] td')).toHaveText(['stock_on_hand', '3', '63'])
  await expect(page.getByText('应用时将按当时生效的配置重新检查')).toBeVisible()
  const approve = page.locator('[data-test=approve]')
  await expect(approve).toBeEnabled()

  // 5. 批准并应用：真实审批证据签发 → 提交 → 同事务消费。
  await approve.click()
  await expect(page.getByText('已批准并应用。')).toBeVisible()
  await expect(approve).toBeDisabled()

  // 6. 库存页：在库 63 > 阈值 5，告警消失。
  await page.goto('/inventory')
  await expect(page.getByText('暂无库存告警。')).toBeVisible()

  // 7. 顾客端公开接口：档位恢复为有货（在库 63 > 阈值 5）。
  expect(await customerStockBand()).toBe('IN_STOCK')

  expect(errors).toEqual([])
})
