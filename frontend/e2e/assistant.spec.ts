import { expect, test, type ConsoleMessage } from '@playwright/test'

function collectConsoleErrors(messages: string[]) {
  return (message: ConsoleMessage) => {
    if (message.type() === 'error') {
      messages.push(message.text())
    }
  }
}

test('助手入口展示 Borough 主布局且无控制台错误', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Borough 商家 AI 助手' })).toBeVisible()
  await expect(page.getByLabel('输入问题')).toBeVisible()
  await expect(page.getByLabel('切换当前演示商家')).toContainText('Borough商家100')

  // 走一整轮流式问答再收口断言：静态首屏本来就不碰 SSE 解析、Adapter 和状态机，
  // 只看首屏的话，流式路径上的报错永远进不了「无控制台错误」的覆盖范围。
  await page.getByTestId('quick-question').first().click()
  await expect(page.getByTestId('stage-label')).toBeVisible()
  // Mock 传输层按字节分块并逐块 sleep，整轮耗时随载荷大小线性增长：B3 的问答图把
  // 步骤从 3 个增加到 13 个之后，一轮要 5 秒以上，正好卡在默认断言窗口边界上。
  // 这里显式给出等待上限，而不是依赖默认值——默认值一变，失败原因会指向错误的地方。
  await expect(page.getByTestId('stage-label')).toHaveCount(0, { timeout: 15_000 })
  await expect(page.getByTestId('chat-message').nth(1)).not.toBeEmpty()

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
  await page.goto('/login')

  await expect(page).toHaveURL('/')
  await expect(page.getByRole('heading', { name: 'Borough 商家 AI 助手' })).toBeVisible()
})

// ---------------------------------------------------------------------------
// 双语本地化（bilingual-localization Task 13）：助手页单页英语烟雾测试。
// 完整的跨页用户旅程在 `e2e/localization.spec.ts`；这里只针对本页做一次
// 独立、聚焦的英语渗透检查，避免以后只改这一页时要跑完整旅程才能发现问题。
// ---------------------------------------------------------------------------

/**
 * 与 `localization.spec.ts` 里的同名 helper 逐字一致（故意不跨文件 import：
 * Playwright 把每个 spec 文件当独立模块加载，跨文件 import 一个内部还调用了
 * 全局 `test`/`expect` 的模块存在把测试注册到错误文件的风险，见该文件顶部
 * 的说明）。
 */
async function expectEnglishOnlyUi(
  page: import('@playwright/test').Page,
  scope?: import('@playwright/test').Locator,
  excludeSelector?: string,
) {
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  const root = scope ?? page.locator('body')
  const failures = await root.evaluate((rootEl, exclude) => {
    const han = /[㐀-鿿]/
    const exempt = (node: Element) =>
      node.closest('[data-l10n-exempt="technical"], [data-l10n-exempt="draft"], code, pre') ||
      (exclude ? node.closest(exclude) : null)
    const visible = (node: Element) => {
      const style = getComputedStyle(node)
      return style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0
    }
    const found: string[] = []
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = (node.parentElement ?? rootEl) as Element
      const text = node.textContent?.trim() ?? ''
      if (text && visible(parent) && !exempt(parent) && han.test(text)) found.push(`text:${text}`)
    }
    for (const node of rootEl.querySelectorAll<HTMLElement>('*')) {
      if (!visible(node) || exempt(node)) continue
      for (const attr of ['aria-label', 'title', 'placeholder']) {
        const value = node.getAttribute(attr)
        if (value && han.test(value)) found.push(`${attr}:${value}`)
      }
      if ((node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement) && han.test(node.value)) {
        found.push(`value:${node.value}`)
      }
    }
    return found
  }, excludeSelector ?? null)
  expect(failures).toEqual([])
}

test('切到英语后，助手首屏头部与空态文案无中文泄漏', async ({ page }) => {
  const errors: string[] = []
  page.on('console', collectConsoleErrors(errors))
  page.on('pageerror', (error) => errors.push(error.message))

  await page.goto('/')
  await page.getByTestId('language-switcher').click()
  await expect(page.getByRole('heading', { name: 'Borough Merchant AI Assistant' })).toBeVisible()

  await expectEnglishOnlyUi(page, page.getByTestId('assistant-header'))
  await expect(page.getByLabel('Ask a question')).toBeVisible()
  await expect(page.getByLabel('Switch current demo merchant')).toContainText('Borough Merchant 100')

  // 空态（尚未提问）的欢迎卡片与四宫格快速问题全部来自 i18n 消息目录或
  // `quickQuestions('en-US')`，与 Mock 夹具词表无关，可以整块审计。
  await expectEnglishOnlyUi(page, page.getByTestId('workspace-column').nth(1))
  // 左侧栏例外：每日经营报告卡片（`DailyReportCard`）的标题本身是 i18n
  // 文案（`t('dailyReportCard.title')`），随 locale 正常变成英语；但里面
  // 的指标名（`metric.displayName`）与建议文案是 Mock `/api/reports/daily`
  // 按 `mockEnglishText()` 词表翻译的，词表没收 `成交金额`/`下单用户数` 等
  // 指标名（另一处「已知缺口」，`frontend/src/api/mock/transport.ts`，不
  // 在本任务文件清单内，未修复，已在 task-13-report.md 报告）。这里先精确
  // 核对第一项指标名现在确实还是中文，再把整块报告卡片排除出审计，指标
  // 定义/图表面板正常参与完整审计。
  // `loadDailyReport()` 只在 `onMounted` 时拉一次，没有随 locale 切换的
  // watcher（另一处已知缺口），所以这条请求到底带哪个 Accept-Language
  // 取决于它和「点语言切换器」谁先完成——可能是切换前的纯中文，也可能是
  // 切换后请求、但词表没覆盖 `成交金额` 而带上 `[en] ` 前缀。用
  // `toContainText` 兼容两种时序，因为两种时序下断言真正关心的事实（中文
  // 原文露出）都成立。
  await expect(page.locator('.daily-report__metrics dt').first()).toContainText('成交金额')
  await expectEnglishOnlyUi(page, page.getByTestId('workspace-column').nth(0), '.daily-report')
  await expectEnglishOnlyUi(page, page.getByTestId('workspace-column').nth(2))

  expect(errors).toEqual([])
})
