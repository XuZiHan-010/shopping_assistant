import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

/**
 * 商家运营助手（`/`，两页合并评审 2026-09-26 评审、2026-09-27 用户裁定「选项 C」
 * 后取代 v1 分析助手 `AssistantView`——PRD §15 N2）。
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

  await page.goto('/')

  await expect(page.getByRole('heading', { name: '运营助手' })).toBeVisible()
  await expect(page.getByTestId('merchant-switcher')).toContainText('Borough商家100')
  await expect(page.getByTestId('language-switcher')).toBeVisible()
  await expect(page.getByLabel('向运营助手提问')).toBeVisible()

  const nav = page.getByRole('navigation', { name: '商家工作台' })
  await expect(nav.getByRole('link', { name: '今日简报' })).toHaveAttribute('href', '/today')
  await expect(nav.getByRole('link', { name: '库存告警' })).toHaveAttribute('href', '/inventory')
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
  await expect(page.getByRole('heading', { name: '运营助手' })).toBeVisible()
})

test('切到英语后，头部与导航文案无中文泄漏', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))
  await mockV2Endpoints(page)

  await page.goto('/')
  await page.getByTestId('language-switcher').click()

  await expect(page.getByRole('heading', { name: 'Operations assistant' })).toBeVisible()
  await expect(page.getByLabel('Ask the operations assistant')).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Merchant workspace' })
  await expect(nav.getByRole('link', { name: "Today's brief" })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Knowledge base' })).toBeVisible()

  expect(errors).toEqual([])
})
