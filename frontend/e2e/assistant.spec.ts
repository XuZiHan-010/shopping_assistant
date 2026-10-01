import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

import { openAssistant, switchLanguage } from './support/assistantRail'
import { mockHomeEndpoints } from './support/v2MerchantMock'

/**
 * 商家运营助手（两页合并评审 2026-09-26 评审、2026-09-27 用户裁定「选项 C」
 * 后取代 v1 分析助手 `AssistantView`——PRD §15 N2）。
 *
 * W Task 6 起助手是常驻外壳、默认收起的助手栏，入口改为 `openAssistant()`
 * （`/?assistant=open`）；原助手页头部的工作台导航与语言切换器随外壳迁到侧栏与
 * 偏好设置，对应断言改指向侧栏「主导航」与偏好设置入口（映射见 W Task 6 报告）。
 *
 * v2 商家会话/聊天走裸 `fetch`（`/api/v2/merchant/*`），不像 v1 `submitChat`
 * 那样经过 `resolveTransport()` 的 Mock 传输层，因此常规 Mock E2E 套件
 * （`VITE_USE_MOCK=true`）从未覆盖过它——现有对 v2 页面的 E2E 覆盖
 * （`e2e/s3/*`）走的是真实后端 + 脚本化模型，是另一套独立配置
 * （`playwright.s3.config.ts`）。这里不新建一套 v2 fetch Mock 基础设施
 * （那是比本次两页合并更大的独立工作），只用 `page.route` 直接 mock 这两个
 * v2 端点，验证首屏可达、无控制台错误、导航入口齐全、`/login` 兜底与语言
 * 切换——完整聊天流程、猜你想问、图表等已有 `e2e/s3/*` 的真实后端覆盖。
 */
async function mockV2Endpoints(page: Page) {
  await page.route('**/api/v2/merchant/sessions', async (route) => {
    await route.fulfill({
      json: {
        session_id: 'e2e-session-id-000000000000000000000000000',
        role: 'MERCHANT',
        expires_at: '2099-01-01T00:00:00Z',
        merchant_display_name: 'Borough商家100',
      },
      status: 201,
    })
  })
  await page.route('**/api/v2/merchant/conversations*', async (route) => {
    await route.fulfill({ json: { items: [], next_cursor: null, has_more: false } })
  })
  // W Task 8：`/` 是首页，空闲后会取简报、主指标等只读数据，一并打桩。
  await mockHomeEndpoints(page)
}

function collectConsoleErrors(messages: string[]) {
  return (message: ConsoleMessage) => {
    if (message.type() === 'error') {
      messages.push(message.text())
    }
  }
}

test('运营助手入口展示商家切换、语言切换与工作台导航，无控制台错误', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))
  await mockV2Endpoints(page)

  await openAssistant(page)

  await expect(page.getByRole('heading', { name: '运营助手' })).toBeVisible()
  await expect(page.getByTestId('merchant-switcher')).toContainText('Borough商家100')
  // 语言切换在偏好设置里（设计说明 §2.1），入口是左下角账号区。
  await expect(page.getByTestId('preferences-trigger')).toBeVisible()
  await expect(page.getByLabel('向运营助手提问')).toBeVisible()

  // 今日简报并入首页（`/today` → `/`），库存告警即侧栏「库存」。
  const nav = page.getByRole('navigation', { name: '主导航' })
  await expect(nav.getByRole('link', { name: '首页' })).toHaveAttribute('href', '/')
  await expect(nav.getByRole('link', { name: '库存' })).toHaveAttribute('href', '/inventory')
  await expect(nav.getByRole('link', { name: '知识库' })).toHaveAttribute('href', '/knowledge-base')

  expect(errors).toEqual([])
})

test('知识库占位页可打开且无控制台错误', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))

  await page.goto('/knowledge-base')

  await expect(page.getByRole('heading', { name: '知识库' })).toBeVisible()
  expect(errors).toEqual([])
})

test('未知路径回到助手入口，不存在登录页', async ({ page }) => {
  await mockV2Endpoints(page)

  await page.goto('/login')

  await expect(page).toHaveURL('/')
  // 助手栏默认收起：从侧栏入口打开后再核对。
  await page.locator('[data-nav-group="assistant"] button').click()
  await expect(page.getByRole('heading', { name: '运营助手' })).toBeVisible()
})

test('切到英语后，头部与导航文案无中文泄漏', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))
  await mockV2Endpoints(page)

  await openAssistant(page)
  await switchLanguage(page, 'en-US')

  await expect(page.getByRole('heading', { name: 'Operations assistant' })).toBeVisible()
  await expect(page.getByLabel('Ask the operations assistant')).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByRole('link', { name: 'Home' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Knowledge base' })).toBeVisible()

  expect(errors).toEqual([])
})

test('Ctrl + J 打开与收起助手栏（输入框聚焦时同样生效，不打开下载页），Esc 收起', async ({
  page,
  context,
}) => {
  await mockV2Endpoints(page)
  await page.goto('/')
  const rail = page.locator('#assistant-rail')
  await expect(rail).toBeHidden()

  await page.keyboard.press('Control+j')
  const input = page.getByLabel('向运营助手提问')
  await expect(input).toBeVisible()
  await expect(input).toBeFocused()

  await page.keyboard.press('Control+j')
  await expect(rail).toBeHidden()
  // Chrome 的 Ctrl + J 默认打开下载页；preventDefault 后不应多出新页面。
  expect(context.pages()).toHaveLength(1)

  await page.locator('[data-nav-group="assistant"] button').click()
  await expect(input).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(rail).toBeHidden()
  await expect(page.locator('[data-nav-group="assistant"] button')).toBeFocused()
})
