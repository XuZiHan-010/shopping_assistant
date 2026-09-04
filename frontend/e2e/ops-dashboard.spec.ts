import { expect, test } from '@playwright/test'

test.describe('Chat BI 看板', () => {
  test('未授权时只显示令牌对话框', async ({ page }) => {
    await page.goto('/ops-dashboard')

    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByTestId('north-star-card')).toHaveCount(0)
  })

  test('授权后显示六项指标与分类下钻', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('mock-admin-token')
    await page.getByRole('button', { name: '进入后台' }).click()

    await expect(page.getByTestId('north-star-card')).toHaveCount(6)
    await expect(
      page.getByTestId('north-star-card').filter({ hasText: '用户侧准确率' }),
    ).toBeVisible()
    await expect(
      page.getByTestId('north-star-card').filter({ hasText: '系统侧准确率' }),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: '按问题分类查看表现' })).toBeVisible()
  })

  test('样本不足时展示说明而不伪造零比率', async ({ page }) => {
    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('mock-admin-token')
    await page.getByRole('button', { name: '进入后台' }).click()

    await expect(page.getByText('样本不足').first()).toBeVisible()
  })

  // -------------------------------------------------------------------------
  // 双语本地化（bilingual-localization Task 13）：看板单页英语渗透测试。
  // 完整跨页旅程在 `e2e/localization.spec.ts`；这里针对本页做一次独立、
  // 完整（除已知缺口外）的 Han 字符扫描，覆盖六项北极星指标、趋势图与
  // 分类下钻表格。
  // -------------------------------------------------------------------------

  test('授权后切到英语，看板整体无中文泄漏（分类名已知缺口除外）', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    page.on('pageerror', (error) => errors.push(error.message))

    await page.goto('/ops-dashboard')
    await page.getByLabel('管理员令牌').fill('mock-admin-token')
    await page.getByRole('button', { name: '进入后台' }).click()
    await expect(page.getByTestId('north-star-card')).toHaveCount(6)

    await page.getByTestId('language-switcher').click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
    await expect(page.getByRole('heading', { name: 'Chat BI operations dashboard' })).toBeVisible()

    // `reloadForLocale`（`frontend/src/stores/analytics.ts`）会在 locale
    // 变化时重新拉一次总览/分类；先等六张卡片和分类表格都用新语言渲染完，
    // 再跑整页审计，避免撞上与 `localization.spec.ts` 主旅程测试同类的
    // 「切换未落地」竞态。
    await expect(page.getByTestId('north-star-card').first()).toContainText('Adoption rate')
    await expect(
      page.getByRole('heading', { name: 'Performance by question category' }),
    ).toBeVisible()

    // `category_display_name` 是 Mock 里硬编码的中文、完全不看
    // Accept-Language（`frontend/src/api/mock/transport.ts` 的
    // `/api/admin/analytics/chatbi/categories` 分支，另一处已知缺口，不在
    // 本任务文件清单内，已在 task-13-report.md 报告），先精确核对分类名
    // 仍是中文，再把这一列排除出整页审计。
    const categoryCells = page.locator('.category-table tbody th')
    await expect(categoryCells.first()).toHaveText('交易分析')

    const han = /[㐀-鿿]/
    const failures = await page.locator('body').evaluate((body, exclude) => {
      const exempt = (node: Element) =>
        node.closest('[data-l10n-exempt="technical"], [data-l10n-exempt="draft"], code, pre') ||
        node.closest(exclude)
      const visible = (node: Element) => {
        const style = getComputedStyle(node)
        return style.display !== 'none' && style.visibility !== 'hidden' && node.getClientRects().length > 0
      }
      const found: string[] = []
      const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const parent = (node.parentElement ?? body) as Element
        const text = node.textContent?.trim() ?? ''
        if (text && visible(parent) && !exempt(parent) && /[㐀-鿿]/.test(text)) {
          found.push(`text:${text}`)
        }
      }
      for (const node of body.querySelectorAll<HTMLElement>('*')) {
        if (!visible(node) || exempt(node)) continue
        for (const attr of ['aria-label', 'title', 'placeholder']) {
          const value = node.getAttribute(attr)
          if (value && /[㐀-鿿]/.test(value)) found.push(`${attr}:${value}`)
        }
      }
      return found
    }, '.category-table tbody th')
    expect(failures).toEqual([])

    const chartCanvas = page.locator('.trend-chart__canvas')
    await expect(chartCanvas).toBeVisible()
    const canvasAria = await chartCanvas.getAttribute('aria-label')
    expect(canvasAria).toBeTruthy()
    expect(canvasAria).not.toMatch(han)

    expect(errors).toEqual([])
  })
})
