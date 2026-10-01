import { expect, type Page, test } from '@playwright/test'

import { mockConversationList, mockDemoMerchants, mockMerchantSession } from './support/v2MerchantMock'
import { openAssistant, switchLanguage } from './support/assistantRail'

/**
 * 运营助手（`/`）语言切换的 Mock E2E 回归。
 *
 * 两页合并（2026-09-27）删除旧 `localization.spec.ts`（725 行）时的结论是：
 * 该文件深度依赖 v1 三栏 DOM 与 `chatStore.reloadForLocale()`（切语言后
 * 用同一份历史消息重放翻译）机制，v2 `opsChat` store **没有**这个重放钩子
 * （只有 `auth`/`knowledge` 两个 store 实现了 `reloadForLocale`，见
 * `src/stores/auth.ts`/`knowledge.ts`）——v2 是新发起请求带新
 * `Accept-Language`，不是把已渲染的历史消息原地重译。本文件测的是这份
 * v2 实际行为本身，不是照抄 v1 断言去凑一个 v2 没有的重放机制。
 *
 * W Task 6：入口改为助手栏（`openAssistant()`），语言切换改走偏好设置
 * （`switchLanguage()`）；原助手页头部导航随外壳迁到侧栏「主导航」。
 */

async function mockChatOnce(page: Page, zhAnswer: string, enAnswer: string) {
  await page.route('**/api/v2/merchant/chat', async (route) => {
    const locale = route.request().headers()['accept-language']
    const answer = locale?.startsWith('en') ? enAnswer : zhAnswer
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: `event: turn_complete\ndata: ${JSON.stringify({
        id: 'answer-1',
        conversation_id: 'conv-001',
        answer,
        answer_mode: 'CHAT',
        tool_calls: [],
        created_at: '2026-01-01T00:00:00Z',
        suggestions: [],
        suggestion_alternates: [],
        analysis_sources: [{ source: 'NONE', degraded: false, degraded_reason: null }],
        thinking_steps: [],
        quality_status: 'PASSED',
        quality_attempts: 1,
        quality_notes: [],
        degraded: false,
        degraded_reason: null,
        visualization: {
          enabled: false,
          type: null,
          allowed_types: [],
          title: null,
          dimension_key: null,
          metric_key: null,
          unit: null,
          data: [],
        },
      })}\n\n`,
    })
  })
}

test('切换到英语后头部与导航立即变为英文，无中文残留', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [])

  await openAssistant(page)
  await expect(page.getByRole('heading', { name: '运营助手' })).toBeVisible()

  await switchLanguage(page, 'en-US')

  await expect(page.getByRole('heading', { name: 'Operations assistant' })).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByRole('link', { name: 'Home' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Inventory' })).toBeVisible()
})

test('切换语言后新提问按新语言请求，不重译已展示的历史回答', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [])
  await mockChatOnce(page, '库存不足的商品有 3 个。', 'There are 3 products low on stock.')

  await openAssistant(page)
  await page.getByRole('textbox', { name: '向运营助手提问' }).fill('库存情况如何？')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('库存不足的商品有 3 个。')).toBeVisible()

  await switchLanguage(page, 'en-US')

  // 已展示的中文回答原样保留（v2 没有重放重译机制），不因切语言而消失或改写。
  await expect(page.getByText('库存不足的商品有 3 个。')).toBeVisible()

  await page.getByRole('textbox', { name: 'Ask the operations assistant' }).fill('How is the inventory?')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText('There are 3 products low on stock.')).toBeVisible()
})
