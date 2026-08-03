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

  const colors = await page
    .locator('.chat-composer__footnote, .side-empty p')
    .evaluateAll((items) => items.map((item) => getComputedStyle(item).color))

  expect(colors).toHaveLength(3)
  for (const color of colors) expect(contrastAgainstWhite(color)).toBeGreaterThanOrEqual(4.5)
})
