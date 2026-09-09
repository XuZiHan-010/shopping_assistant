import { expect, test } from '@playwright/test'

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

test('1440px 保持三栏及宽度约束', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')

  const columns = page.getByTestId('workspace-column')
  await expect(columns).toHaveCount(3)

  const widths = await columns.evaluateAll((items) =>
    items.map((item) => item.getBoundingClientRect().width),
  )
  expect(widths[0]).toBeGreaterThanOrEqual(230)
  expect(widths[0]).toBeLessThanOrEqual(280)
  expect(widths[1]).toBeLessThanOrEqual(760)
  expect(widths[2]).toBeGreaterThanOrEqual(230)
  expect(widths[2]).toBeLessThanOrEqual(280)
})

for (const width of [561, 580]) {
  test(`${width}px 顶栏不换行或溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/')

    const headerSize = await page.getByTestId('assistant-header').evaluate((header) => ({
      clientWidth: header.clientWidth,
      scrollWidth: header.scrollWidth,
    }))
    expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)
  })
}

test('390px 输入区可见且可聚焦', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  const input = page.getByLabel('输入问题')
  await expect(input).toBeVisible()
  await input.focus()
  await expect(input).toBeFocused()
})

test('360px 没有页面级横向滚动', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 844 })
  await page.goto('/')

  const dimensions = await page.evaluate(() => {
    const root = document.scrollingElement
    return { clientWidth: root?.clientWidth ?? 0, scrollWidth: root?.scrollWidth ?? 0 }
  })
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
})

test('减少动画偏好会缩短交互过渡', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')

  const duration = await page
    .locator('.new-chat-button')
    .evaluate((button) => Number.parseFloat(getComputedStyle(button).transitionDuration))
  expect(duration).toBeLessThan(0.001)
})

test('输入提示和侧栏说明文字达到 WCAG AA 对比度', async ({ page }) => {
  await page.goto('/')

  // F1 的 .side-empty 在 F2 Task 8 被三个真实侧栏面板取代，选择器随之更新。
  // 用 data-testid 而不是 CSS 类名，避免下次改样式时又静默只剩一个元素匹配。
  const colors = await page
    .locator(
      [
        '.chat-composer__footnote',
        '[data-testid="metric-empty"] > *',
        '[data-testid="chart-empty"] > *',
        '[data-testid="recommendation-empty"] > *',
      ].join(', '),
    )
    .evaluateAll((items) => items.map((item) => getComputedStyle(item).color))

  // 该选择器包含一个 footnote 容器和两个空态面板各自的标题、说明，共 5 项。
  expect(colors).toHaveLength(5)
  for (const color of colors) expect(contrastAgainstWhite(color)).toBeGreaterThanOrEqual(4.5)
})

// ---------------------------------------------------------------------------
// 双语本地化 Step 4：响应式与焦点（bilingual-localization Task 13）。
// ---------------------------------------------------------------------------

test('360px 英语模式下头部按钮不溢出、语言切换器不遮挡商家切换器', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 844 })
  await page.goto('/')
  await page.getByTestId('language-switcher').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')

  const headerSize = await page.getByTestId('assistant-header').evaluate((header) => ({
    clientWidth: header.clientWidth,
    scrollWidth: header.scrollWidth,
  }))
  expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)

  // 360px 下页头改用两行网格（`nav logo title actions` / `. merchant merchant .`，
  // 见 `AssistantView.vue` 的 `@media (max-width: 560px)`），语言切换器和
  // 商家切换器因此天然不在同一行——这里直接量出两者的包围盒，确认真的没有
  // 重叠，而不是只信任 CSS 网格区域名字。
  const merchantBox = await page.getByTestId('merchant-switcher').boundingBox()
  const languageBox = await page.getByTestId('language-switcher').boundingBox()
  expect(merchantBox).not.toBeNull()
  expect(languageBox).not.toBeNull()
  if (merchantBox && languageBox) {
    const overlapsHorizontally =
      merchantBox.x < languageBox.x + languageBox.width && languageBox.x < merchantBox.x + merchantBox.width
    const overlapsVertically =
      merchantBox.y < languageBox.y + languageBox.height && languageBox.y < merchantBox.y + merchantBox.height
    expect(overlapsHorizontally && overlapsVertically).toBe(false)
  }

  const dimensions = await page.evaluate(() => {
    const root = document.scrollingElement
    return { clientWidth: root?.clientWidth ?? 0, scrollWidth: root?.scrollWidth ?? 0 }
  })
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
})

test('1440px 英语模式下三栏与头部保持既有宽度约束', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await page.getByTestId('language-switcher').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')

  const columns = page.getByTestId('workspace-column')
  await expect(columns).toHaveCount(3)
  const widths = await columns.evaluateAll((items) => items.map((item) => item.getBoundingClientRect().width))
  expect(widths[0]).toBeGreaterThanOrEqual(230)
  expect(widths[0]).toBeLessThanOrEqual(280)
  expect(widths[2]).toBeGreaterThanOrEqual(230)
  expect(widths[2]).toBeLessThanOrEqual(280)

  const headerSize = await page.getByTestId('assistant-header').evaluate((header) => ({
    clientWidth: header.clientWidth,
    scrollWidth: header.scrollWidth,
  }))
  expect(headerSize.scrollWidth).toBeLessThanOrEqual(headerSize.clientWidth)

  // 英语文案比中文长（"Dashboard"/"Knowledge base"/"New chat" 等），1440px
  // 下头部一整排按钮理应还有富余——头部整体不溢出之外，再单独确认每个
  // 可交互控件本身的包围盒没有超出头部右边界。
  const headerBox = await page.getByTestId('assistant-header').boundingBox()
  const actionBoxes = await Promise.all(
    [
      page.getByTestId('language-switcher'),
      page.getByRole('link', { name: 'Knowledge base maintenance' }),
      page.getByRole('link', { name: 'Chat BI operations dashboard' }),
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

test('键盘切换语言后焦点回到切换按钮，看板的 aria-live 加载态用目标语言播报', async ({ page }) => {
  await page.goto('/ops-dashboard')
  await page.getByLabel('管理员令牌').fill('mock-admin-token')
  await page.getByRole('button', { name: '进入后台' }).click()
  await expect(page.getByTestId('north-star-card')).toHaveCount(6)

  const switcher = page.getByTestId('language-switcher')
  await switcher.focus()
  await expect(switcher).toBeFocused()

  // `analyticsStore` 在 locale 变化时会重新拉一次总览/分类
  // （`reloadForLocale`，见 `frontend/src/stores/analytics.ts`），期间渲染
  // 一条 `aria-live="polite"` 的加载提示（`.ops-dashboard__loading`）。
  // 用 MutationObserver 而不是轮询断言来捕获这条提示：Mock 请求可能在个位数
  // 毫秒内完成，轮询容易整个错过这次插入/移除，MutationObserver 是在同一个
  // JS 事件循环里同步注册、不依赖真实时钟节奏的捕获方式。
  const capture = page.evaluate(() => {
    return new Promise<string[]>((resolve) => {
      const seen: string[] = []
      const record = (el: Element) => {
        const text = el.textContent?.trim()
        if (text) seen.push(text)
      }
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          for (const node of Array.from(mutation.addedNodes)) {
            if (!(node instanceof Element)) continue
            if (node.matches('[aria-live]')) record(node)
            node.querySelectorAll('[aria-live]').forEach(record)
          }
        }
      })
      observer.observe(document.body, { subtree: true, childList: true })
      setTimeout(() => {
        observer.disconnect()
        resolve(seen)
      }, 1000)
    })
  })

  // 键盘激活：Tab 已经把焦点交给了这个真正的 <button>（上面 focus() 模拟的
  // 就是这一步的结果），Enter 触发原生的按钮激活行为。
  await switcher.press('Enter')
  const announcements = await capture

  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  // 键盘切换后焦点必须留在触发按钮上，不能被随后的重新渲染带跑。
  await expect(switcher).toBeFocused()

  const hasEnglishAnnouncement = announcements.some(
    (text) => /[a-zA-Z]/.test(text) && !/[㐀-鿿]/.test(text),
  )
  expect(hasEnglishAnnouncement).toBe(true)

  // 再切回中文，确认反方向同样成立：焦点仍在按钮上，播报文本不再是英语。
  const captureBack = page.evaluate(() => {
    return new Promise<string[]>((resolve) => {
      const seen: string[] = []
      const record = (el: Element) => {
        const text = el.textContent?.trim()
        if (text) seen.push(text)
      }
      const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
          for (const node of Array.from(mutation.addedNodes)) {
            if (!(node instanceof Element)) continue
            if (node.matches('[aria-live]')) record(node)
            node.querySelectorAll('[aria-live]').forEach(record)
          }
        }
      })
      observer.observe(document.body, { subtree: true, childList: true })
      setTimeout(() => {
        observer.disconnect()
        resolve(seen)
      }, 1000)
    })
  })
  await switcher.press('Enter')
  const announcementsBack = await captureBack
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN')
  await expect(switcher).toBeFocused()
  const hasChineseAnnouncement = announcementsBack.some((text) => /[㐀-鿿]/.test(text))
  expect(hasChineseAnnouncement).toBe(true)
})
