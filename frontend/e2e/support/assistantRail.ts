import type { Page } from '@playwright/test'

/**
 * 助手栏的 E2E 入口（W Task 6）。
 *
 * W 阶段起 `/` 是首页，运营助手改为常驻外壳、默认收起的助手栏；对话历史在助手栏头部的
 * 「历史」面板里，语言切换在左下角账号区的「偏好设置」里。原先 `page.goto('/')` 即到
 * 助手整页的用例，统一改从这里进入——只换入口，后续断言不变。
 */

/** 从 `/?assistant=open`（`/ops-assistant` 旧地址的落点，裁定 A）进入并打开助手栏。 */
export async function openAssistant(
  page: Page,
  options: { history?: boolean } = {},
): Promise<void> {
  await page.goto('/?assistant=open')
  await page.locator('#assistant-rail:not([hidden])').waitFor()
  if (options.history) await openHistory(page)
}

/** 展开助手栏头部的「历史」面板（会话目录：新建、浏览、打开、删除）。 */
export async function openHistory(page: Page): Promise<void> {
  const toggle = page.locator('[data-test="rail-history-toggle"]')
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') await toggle.click()
  await page.locator('#assistant-rail-history').waitFor()
}

/**
 * 经偏好设置切换界面语言（原助手页头部的语言切换器已并入偏好面板）。
 * 窄屏（820px 以下）侧栏是抽屉，先打开抽屉；助手栏抽屉若盖着页面，先按 Escape 收起。
 * 切换后按 Escape 关面板、关抽屉，并重新打开助手栏，回到切换前的界面状态。
 */
export async function switchLanguage(page: Page, locale: 'zh-CN' | 'en-US'): Promise<void> {
  const trigger = page.getByTestId('preferences-trigger')
  const drawer = !(await trigger.isVisible())
  const railCovering = drawer && (await page.getByTestId('rail-backdrop').isVisible())
  if (railCovering) {
    await page.keyboard.press('Escape')
    await page.locator('#assistant-rail[hidden]').waitFor({ state: 'attached' })
  }
  if (drawer) {
    await page.locator('[aria-controls="side-nav"]').click()
    await trigger.waitFor()
  }
  await trigger.click()
  await page.locator('select[name="language"]').selectOption(locale)
  await page
    .locator('html')
    .and(page.locator(`[lang="${locale}"]`))
    .waitFor({ state: 'attached' })
  await page.keyboard.press('Escape')
  if (drawer) await page.keyboard.press('Escape')
  if (railCovering) {
    await page.locator('.shell__assist-top').click()
    await page.locator('#assistant-rail:not([hidden])').waitFor()
  }
}
