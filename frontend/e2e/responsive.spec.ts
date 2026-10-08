import { expect, test, type Page } from '@playwright/test'

import { openAssistant, switchLanguage } from './support/assistantRail'
import { expectNoHorizontalOverflow } from './support/overflow'
import { mockHomeEndpoints } from './support/v2MerchantMock'

function contrastAgainstWhite(cssColor: string): number {
  const channels = cssColor
    .match(/\d+(?:\.\d+)?/g)
    ?.slice(0, 3)
    .map(Number)
  if (!channels || channels.length !== 3) throw new Error(`无法解析颜色：${cssColor}`)

  const luminance = channels
    .map((channel) => channel / 255)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4))
    .reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0)

  return 1.05 / (luminance + 0.05)
}

/**
 * 两页合并（2026-09-26 评审、2026-09-27 用户裁定「选项 C」）后 `/` 是 v2
 * 运营助手（`OpsAssistantView`），不再是 v1 三栏 `AssistantView`；断点也从
 * v1 的 560px 改为 v2 CSS 的 40rem（640px）。这里改用 `mockV2Endpoints`
 * 让页面在无真实后端时也能挂载出商家/语言切换器、会话目录与聊天区。
 *
 * W Task 6 起助手是常驻外壳、默认收起的助手栏（1100px 以下为带遮罩的抽屉），
 * 会话目录在助手栏「历史」面板里，语言切换在偏好设置里。入口改为 `openAssistant()`；
 * 原「会话目录 | 聊天区」两栏、头部语言切换器等随设计取消的布局，断言改指向新布局中
 * 承担同一约束的元素（逐条映射见 W Task 6 报告）。
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

test('1101px（刚过助手栏抽屉断点）保持并排：主视图与助手栏聊天区并排', async ({ page }) => {
  // 会话目录已移进助手栏「历史」面板（与聊天区互斥显示），并排约束改由「主视图 | 助手栏」
  // 承担；1100px 及以下助手栏按设计改为抽屉，因此断点从 641px 移到 1101px。
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 1101, height: 1000 })
  await openAssistant(page)

  const directory = page.locator('main#main')
  const chat = page.getByRole('region', { name: '运营助手' })
  await expect(directory).toBeVisible()
  await expect(chat).toBeVisible()

  const [directoryBox, chatBox] = await Promise.all([directory.boundingBox(), chat.boundingBox()])
  expect(directoryBox).not.toBeNull()
  expect(chatBox).not.toBeNull()
  if (directoryBox && chatBox) {
    // 并排：主视图在聊天区左边，纵向范围重叠（同一行），不是上下堆叠或被抽屉盖住。
    expect(directoryBox.x + directoryBox.width).toBeLessThanOrEqual(chatBox.x + 1)
    expect(directoryBox.y).toBeLessThan(chatBox.y + chatBox.height)
  }
})

for (const width of [561, 580]) {
  test(`${width}px 顶栏不换行溢出`, async ({ page }) => {
    await mockV2Endpoints(page)
    await page.setViewportSize({ width, height: 844 })
    await openAssistant(page)

    const headerSize = await page.getByTestId('ops-header').evaluate((header) => ({
      clientWidth: header.clientWidth,
      scrollWidth: header.scrollWidth,
    }))
    expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)
  })
}

test('390px 输入区可见且可聚焦', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await openAssistant(page)

  const input = page.getByLabel('向运营助手提问')
  await expect(input).toBeVisible()
  await input.focus()
  await expect(input).toBeFocused()
})

test('360px 没有页面级横向滚动', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 360, height: 844 })
  await page.goto('/')
  await page.locator('main#main').waitFor()

  await expectNoHorizontalOverflow(page, '360px 首页')
})

test('减少动画偏好会缩短交互过渡（全局 base.css 规则，用商家切换器验证）', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')

  const duration = await page
    .getByTestId('merchant-switcher')
    .evaluate((button) => Number.parseFloat(getComputedStyle(button).transitionDuration))
  expect(duration).toBeLessThan(0.001)
})

test('草稿范围说明与空态文字达到 WCAG AA 对比度', async ({ page }) => {
  await mockV2Endpoints(page)
  await openAssistant(page)

  const colors = await page
    .locator(['.ops-view__scope', '.ops-view__muted'].join(', '))
    .evaluateAll((items) => items.map((item) => getComputedStyle(item).color))

  expect(colors.length).toBeGreaterThan(0)
  for (const color of colors) expect(contrastAgainstWhite(color)).toBeGreaterThanOrEqual(4.5)
})

// ---------------------------------------------------------------------------
// 双语本地化：响应式与焦点（v1 时期为 bilingual-localization Task 13；
// 两页合并后改用 v2 页面验证同一条意图）。
// ---------------------------------------------------------------------------

test('360px 英语模式下头部不溢出、语言切换器与商家切换器不重叠', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 360, height: 844 })
  await openAssistant(page)
  await switchLanguage(page, 'en-US')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')

  const headerSize = await page.getByTestId('ops-header').evaluate((header) => ({
    clientWidth: header.clientWidth,
    scrollWidth: header.scrollWidth,
  }))
  expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)

  // 商家切换与语言切换（偏好设置入口）都在侧栏里；360px 下助手栏与侧栏都是抽屉，
  // 先按 Escape 收起盖住页面的助手栏，再打开侧栏抽屉。
  await page.keyboard.press('Escape')
  await page.locator('[aria-controls="side-nav"]').click()
  await expect(page.getByTestId('preferences-trigger')).toBeVisible()
  const merchantBox = await page.getByTestId('merchant-switcher').boundingBox()
  const languageBox = await page.getByTestId('preferences-trigger').boundingBox()
  expect(merchantBox).not.toBeNull()
  expect(languageBox).not.toBeNull()
  if (merchantBox && languageBox) {
    const overlapsHorizontally =
      merchantBox.x < languageBox.x + languageBox.width &&
      languageBox.x < merchantBox.x + merchantBox.width
    const overlapsVertically =
      merchantBox.y < languageBox.y + languageBox.height &&
      languageBox.y < merchantBox.y + merchantBox.height
    expect(overlapsHorizontally && overlapsVertically).toBe(false)
  }

  await expectNoHorizontalOverflow(page, '360px 英语侧栏抽屉')
})

test('1440px 英语模式下两栏与头部保持既有宽度约束', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await openAssistant(page)
  await switchLanguage(page, 'en-US')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')

  const headerSize = await page.getByTestId('ops-header').evaluate((header) => ({
    clientWidth: header.clientWidth,
    scrollWidth: header.scrollWidth,
  }))
  expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)

  // 英语文案比中文长（"Operations assistant"/"History" 等），助手栏头部固定 400px 宽——
  // 头部整体不溢出之外，再单独确认每个可交互控件本身的包围盒没有超出头部右边界。
  // （原头部的导航链接与语言切换器已迁到侧栏与偏好设置，这里改核对助手栏头部的控件。）
  const headerBox = await page.getByTestId('ops-header').boundingBox()
  const actionBoxes = await Promise.all(
    [
      page.locator('[data-test="rail-history-toggle"]'),
      page.getByRole('button', { name: 'New conversation' }),
      page.getByRole('button', { name: 'Close assistant' }).and(page.locator('[data-test]')),
    ].map((locator) => locator.boundingBox()),
  )
  expect(headerBox).not.toBeNull()
  for (const box of actionBoxes) {
    expect(box).not.toBeNull()
    if (headerBox && box) {
      expect(box.x + box.width).toBeLessThanOrEqual(headerBox.x + headerBox.width + 1)
    }
  }
})

test('375px 助手栏抽屉打开（含历史面板与长文本）时没有页面级横向滚动', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.route('**/api/v2/merchant/conversations*', async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: 'c-long',
            title: 'ORDER-REF-' + 'X'.repeat(90),
            created_at: '2026-09-27T00:00:00Z',
            updated_at: '2026-09-27T00:00:00Z',
          },
        ],
        next_cursor: null,
        has_more: false,
      },
    })
  })
  await page.setViewportSize({ width: 375, height: 812 })
  await openAssistant(page)

  // 抽屉铺满视口宽度，遮罩在下面；聊天区与输入框都在视口内。
  const railBox = await page.locator('#assistant-rail').boundingBox()
  expect(railBox).not.toBeNull()
  if (railBox) expect(railBox.x + railBox.width).toBeLessThanOrEqual(375 + 1)
  await expect(page.getByTestId('rail-backdrop')).toBeAttached()
  await expectNoHorizontalOverflow(page, '375px 助手栏对话面板')

  await page.locator('[data-test="rail-history-toggle"]').click()
  await expect(page.getByText('ORDER-REF-', { exact: false })).toBeVisible()
  await expectNoHorizontalOverflow(page, '375px 助手栏历史面板')
})
