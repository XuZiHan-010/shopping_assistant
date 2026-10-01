import { expect, test } from '@playwright/test'

import {
  DEMO_MERCHANT_A,
  MOCK_DEMO_TOKENS,
  mockConversationDetail,
  mockConversationList,
  mockDeleteConversation,
  mockDemoMerchants,
  mockMerchantChat,
  mockMerchantFeedback,
  mockMerchantSession,
  mockSessionIdFor,
} from './support/v2MerchantMock'
import { openAssistant } from './support/assistantRail'

/**
 * 运营助手（`/`，v2 商家 Chat）核心问答与目录场景的 Mock E2E 回归。
 *
 * 两页合并（2026-09-27）删除旧 `conversation.spec.ts` 时的结论是：v2 层从未
 * 接入过 v1 `mock/transport.ts` 那套 fixture 拦截基础设施，需要先补一层再
 * 重建场景（见 `e2e/support/v2MerchantMock.ts` 头部说明）。本文件用那层
 * 基础设施重建等价覆盖——不是逐条照抄旧用例断言的 DOM 结构（v1 三栏 vs
 * v2 两栏、`quick-question` fixture 索引等 v1 专属机制在 v2 不存在），而是
 * 验证同一组产品行为：一问一答、打开历史对话恢复内容、
 * 删除会话从目录移除、采纳与赞踩持久化。
 *
 * W Task 6 起助手是常驻外壳的助手栏：入口改为 `openAssistant()`，会话目录在
 * 「历史」面板里（`{ history: true }`）；后续断言不变。
 *
 * 注意：本页组件用 `data-test="..."` 属性（不是 `data-testid`），因此定位
 * 一律用 `page.locator('[data-test="..."]')`，不用 `getByTestId()`。
 */

function byTest(page: import('@playwright/test').Page, name: string) {
  return page.locator(`[data-test="${name}"]`)
}

test('发送问题后展示回答', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [])
  await mockMerchantChat(page, [
    { answer: '最近 7 天有 3 个商品库存不足。', answerMode: 'METRIC', conversationId: 'conv-001' },
  ])

  await openAssistant(page)
  await page.getByRole('textbox', { name: '向运营助手提问' }).fill('哪些商品库存不足？')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('最近 7 天有 3 个商品库存不足。')).toBeVisible()
})

test('打开历史对话恢复消息内容', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [{ id: 'conv-001', title: '库存问题' }])
  await mockConversationDetail(page, 'conv-001', { id: 'conv-001', title: '库存问题' }, [
    { id: 'm1', role: 'user', content: '哪些商品库存不足？' },
    {
      id: 'm2',
      role: 'assistant',
      content: '最近 7 天有 3 个商品库存不足。',
      turn: { answer: '最近 7 天有 3 个商品库存不足。', answerMode: 'METRIC', conversationId: 'conv-001' },
    },
  ])

  await openAssistant(page, { history: true })
  await byTest(page, 'ops-conversation-item').locator('[data-test="ops-conversation-open"]').click()

  await expect(page.getByText('哪些商品库存不足？')).toBeVisible()
  await expect(page.getByText('最近 7 天有 3 个商品库存不足。')).toBeVisible()
})

test('打开历史对话后点「新建对话」清空页面，下一条消息开启新会话', async ({ page }) => {
  // PRD §12.4「新建、浏览、跳转、删除」中的「新建」：目录按钮此前在单测与 E2E 中都无覆盖。
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [{ id: 'conv-001', title: '库存问题' }])
  await mockConversationDetail(page, 'conv-001', { id: 'conv-001', title: '库存问题' }, [
    { id: 'm1', role: 'user', content: '哪些商品库存不足？' },
    {
      id: 'm2',
      role: 'assistant',
      content: '最近 7 天有 3 个商品库存不足。',
      turn: { answer: '最近 7 天有 3 个商品库存不足。', answerMode: 'METRIC', conversationId: 'conv-001' },
    },
  ])
  await mockMerchantChat(page, [{ answer: '你好，我能帮你查询经营数据。', answerMode: 'CHAT', conversationId: 'conv-002' }])
  const chatBodies: Array<Record<string, unknown>> = []
  // 后注册的处理器优先：只记录请求体，再交回 mockMerchantChat 返回固定回答。
  await page.route('**/api/v2/merchant/chat', async (route) => {
    if (route.request().method() === 'POST') chatBodies.push(route.request().postDataJSON())
    await route.fallback()
  })

  await openAssistant(page, { history: true })
  const openButton = byTest(page, 'ops-conversation-open')
  await openButton.click()
  await expect(page.getByText('哪些商品库存不足？')).toBeVisible()
  await expect(openButton).toHaveAttribute('aria-current', 'true')

  await page.getByRole('button', { name: '新建对话' }).click()

  await expect(page.getByText('哪些商品库存不足？')).toHaveCount(0)
  await expect(openButton).not.toHaveAttribute('aria-current', 'true')

  await page.getByRole('textbox', { name: '向运营助手提问' }).fill('你好')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('你好，我能帮你查询经营数据。')).toBeVisible()
  expect(chatBodies).toHaveLength(1)
  expect(chatBodies[0].conversation_id ?? null).toBeNull()
})

test('删除会话后从目录中移除', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [{ id: 'conv-001', title: '库存问题' }])
  await mockDeleteConversation(page)

  await openAssistant(page, { history: true })
  await expect(byTest(page, 'ops-conversation-item')).toHaveCount(1)

  await byTest(page, 'ops-conversation-delete').click()

  await expect(byTest(page, 'ops-conversation-item')).toHaveCount(0)
})

test('采纳与点赞回执持久化展示', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page)
  await mockConversationList(page, [])
  await mockMerchantChat(page, [
    { answer: '最近 7 天有 3 个商品库存不足。', answerMode: 'METRIC', conversationId: 'conv-001' },
  ])
  await mockMerchantFeedback(page)

  await openAssistant(page)
  await page.getByRole('textbox', { name: '向运营助手提问' }).fill('哪些商品库存不足？')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.getByText('最近 7 天有 3 个商品库存不足。')).toBeVisible()

  await byTest(page, 'ops-adopt').click()
  await expect(byTest(page, 'ops-adopt')).toHaveAttribute('aria-pressed', 'true')

  await byTest(page, 'ops-like').click()
  await expect(byTest(page, 'ops-like')).toHaveAttribute('aria-pressed', 'true')
})

test('商家切换后清空会话与目录', async ({ page }) => {
  await mockDemoMerchants(page)
  await mockMerchantSession(page, DEMO_MERCHANT_A.displayName)
  // 目录只属于商家 A（按 X-Session-Id 区分）：切换到 B 后重新拉取目录得到空列表，
  // 断言因此稳定检验「切换清空且不再显示 A 的会话」，而不是赶在重新拉取前的短窗口。
  await mockConversationList(page, [{ id: 'conv-001', title: '库存问题' }], {
    ownerToken: MOCK_DEMO_TOKENS['Borough商家100'],
  })
  await mockMerchantChat(page, [{ answer: '你好，我能帮你查询经营数据。', answerMode: 'CHAT' }])

  await openAssistant(page, { history: true })
  await expect(byTest(page, 'ops-conversation-item')).toHaveCount(1)

  // 等切换后用商家 B 的会话重新拉取目录完成，再断言为空：此时若仍显示 A 的会话即为缺陷。
  const reloadedForB = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      new URL(response.url()).pathname.endsWith('/api/v2/merchant/conversations') &&
      response.request().headers()['x-session-id'] ===
        mockSessionIdFor(MOCK_DEMO_TOKENS['Borough商家101']),
  )
  await page.getByLabel('切换当前演示商家').click()
  await page.locator('[role="option"][data-merchant="Borough商家101"]').click()
  await reloadedForB

  await expect(byTest(page, 'ops-conversation-item')).toHaveCount(0)
})
