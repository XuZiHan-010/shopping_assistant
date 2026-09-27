import { expect, test } from '@playwright/test'

/**
 * F3 Task 7：Playwright 强制 VITE_USE_MOCK=true 跑 e2e，若隔离只由一张全局
 * 会话表兜底，这条断言在 Mock 上永远为真、在真实后端商家隔离被打破时也不会
 * 报警——是假绿。v1 `AssistantView` 时期靠 v1 mock 传输层按收到的 Authorization
 * 头分租户来验证这一点；两页合并（2026-09-27，选项 C）后 `/` 换成走裸 `fetch`
 * 的 v2 `OpsAssistantView`，这里改用 `page.route` 按 `X-Session-Id` 头分桶，
 * 模拟服务端「不同会话看不到彼此会话目录」这条隔离行为，断言的是同一件事：
 * 切换商家换发新会话后，目录不会露出上一个商家的数据。
 */
test('切换商家后看不到上一个商家的会话', async ({ page }) => {
  const sessionByAuthorization = new Map<string, string>()
  const conversationsBySession = new Map<string, unknown[]>([
    [
      'e2e-session-a'.padEnd(43, '0'),
      [
        {
          id: 'c-100',
          title: '商家 A 的会话',
          created_at: '2026-09-27T00:00:00Z',
          updated_at: '2026-09-27T00:00:00Z',
        },
      ],
    ],
  ])

  await page.route('**/api/v2/merchant/sessions', async (route) => {
    const authorization = route.request().headers().authorization ?? ''
    let sessionId = sessionByAuthorization.get(authorization)
    if (!sessionId) {
      sessionId = `e2e-session-${sessionByAuthorization.size === 0 ? 'a' : 'b'}`.padEnd(43, '0')
      sessionByAuthorization.set(authorization, sessionId)
    }
    await route.fulfill({
      status: 201,
      json: {
        session_id: sessionId,
        role: 'MERCHANT',
        expires_at: '2099-01-01T00:00:00Z',
        merchant_display_name: 'Borough商家',
      },
    })
  })
  await page.route('**/api/v2/merchant/conversations*', async (route) => {
    const sessionId = route.request().headers()['x-session-id'] ?? ''
    const items = conversationsBySession.get(sessionId) ?? []
    await route.fulfill({ json: { items, next_cursor: null, has_more: false } })
  })

  await page.goto('/')

  // 商家 A（默认选中的 Borough商家100）能看到自己的会话。
  await expect(page.getByText('商家 A 的会话')).toBeVisible()

  // 切到商家 B——换会话后目录不该带着商家 A 的数据。
  await page.getByTestId('merchant-switcher').click()
  await page.locator('[data-merchant="Borough商家101"]').click()

  await expect(page.getByText('还没有历史对话。')).toBeVisible()
  await expect(page.getByText('商家 A 的会话')).toHaveCount(0)
})
