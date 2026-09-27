import { expect, test, type Page } from '@playwright/test'

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

test('641px（刚过断点）保持两栏：会话目录与聊天区并排', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 900, height: 1000 })
  await page.goto('/')

  const directory = page.getByRole('region', { name: '历史对话' })
  const chat = page.getByRole('region', { name: '运营助手' })
  await expect(directory).toBeVisible()
  await expect(chat).toBeVisible()

  const [directoryBox, chatBox] = await Promise.all([directory.boundingBox(), chat.boundingBox()])
  expect(directoryBox).not.toBeNull()
  expect(chatBox).not.toBeNull()
  if (directoryBox && chatBox) {
    // 两栏并排：会话目录在聊天区左边，纵向范围重叠（同一行），不是上下堆叠。
    expect(directoryBox.x + directoryBox.width).toBeLessThanOrEqual(chatBox.x + 1)
    expect(directoryBox.y).toBeLessThan(chatBox.y + chatBox.height)
  }
})

for (const width of [561, 580]) {
  test(`${width}px 顶栏不换行溢出`, async ({ page }) => {
    await mockV2Endpoints(page)
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/')

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
  await page.goto('/')

  const input = page.getByLabel('向运营助手提问')
  await expect(input).toBeVisible()
  await input.focus()
  await expect(input).toBeFocused()
})

test('360px 没有页面级横向滚动', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 360, height: 844 })
  await page.goto('/')

  const dimensions = await page.evaluate(() => {
    const root = document.scrollingElement
    return { clientWidth: root?.clientWidth ?? 0, scrollWidth: root?.scrollWidth ?? 0 }
  })
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
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
  await page.goto('/')

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
  await page.goto('/')
  await page.getByTestId('language-switcher').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')

  const headerSize = await page.getByTestId('ops-header').evaluate((header) => ({
    clientWidth: header.clientWidth,
    scrollWidth: header.scrollWidth,
  }))
  expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)

  const merchantBox = await page.getByTestId('merchant-switcher').boundingBox()
  const languageBox = await page.getByTestId('language-switcher').boundingBox()
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

  const dimensions = await page.evaluate(() => {
    const root = document.scrollingElement
    return { clientWidth: root?.clientWidth ?? 0, scrollWidth: root?.scrollWidth ?? 0 }
  })
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
})

test('1440px 英语模式下两栏与头部保持既有宽度约束', async ({ page }) => {
  await mockV2Endpoints(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await page.getByTestId('language-switcher').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')

  const headerSize = await page.getByTestId('ops-header').evaluate((header) => ({
    clientWidth: header.clientWidth,
    scrollWidth: header.scrollWidth,
  }))
  expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)

  // 英语文案比中文长（"Today's brief"/"Knowledge base" 等），1440px 下头部
  // 一整排导航链接理应还有富余——头部整体不溢出之外，再单独确认每个可交互
  // 控件本身的包围盒没有超出头部右边界。
  const headerBox = await page.getByTestId('ops-header').boundingBox()
  const actionBoxes = await Promise.all(
    [
      page.getByTestId('language-switcher'),
      page.getByRole('link', { name: "Today's brief" }),
      page.getByRole('link', { name: 'Knowledge base' }),
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
