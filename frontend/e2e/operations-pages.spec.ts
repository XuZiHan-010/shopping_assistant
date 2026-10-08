/**
 * W Task 10 换样式页面的视觉健全性 Mock E2E：库存、待审批、审批详情、售后（含详情）、
 * 顾客信号、商家记忆、知识库（授权前后）在 375px 的浅色与深色下都没有横向溢出；
 * 深色下面板不是白底；知识库不再嵌套第二个 <main>，且只有一个语言切换器。
 */
import { expect, test, type ConsoleMessage, type Locator, type Page } from '@playwright/test'

import { mockOpsAssistantShell } from './support/v2MerchantMock'
import { expectNoHorizontalOverflow } from './support/overflow'
import { E2E_DRAFT_ID, mockCatalogPage, mockOperationsPages } from './support/workspaceMock'

const WHITE = 'rgb(255, 255, 255)'

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function expectNotWhite(locator: Locator, state: string) {
  const background = await locator.evaluate((node) => getComputedStyle(node).backgroundColor)
  expect(background, `${state}：深色下仍是白底`).not.toBe(WHITE)
}

for (const theme of ['light', 'dark'] as const) {
  test(`375px ${theme === 'light' ? '浅色' : '深色'}：换样式的运营页与知识库都没有横向溢出`, async ({
    page,
  }) => {
    const errors = trackConsoleErrors(page)
    await page.setViewportSize({ width: 375, height: 812 })
    await page.addInitScript((value) => window.localStorage.setItem('borough.theme', value), theme)
    await mockOpsAssistantShell(page)
    await mockCatalogPage(page)
    await mockOperationsPages(page)
    const dark = theme === 'dark'

    // 库存：告警表格（窄屏改卡片）+ 商品内容卡片 + 优惠券卡片
    await page.goto('/inventory')
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await expect(page.getByRole('heading', { level: 1, name: '库存告警' })).toBeVisible()
    await expect(page.getByRole('row', { name: /轻量通勤夹克/ })).toBeVisible()
    await expect(page.locator('.inventory-view__cards li')).toHaveCount(4)
    await expectNoHorizontalOverflow(page, `${theme} 库存`)
    if (dark) await expectNotWhite(page.locator('.ws-panel').first(), '库存面板')

    // 待审批：批次分组 + 单独草稿
    await page.goto('/approvals')
    await expect(page.locator('[data-test=draft-group]')).toHaveCount(2)
    await expect(page.getByRole('main').getByRole('listitem')).toHaveCount(3)
    await expectNoHorizontalOverflow(page, `${theme} 待审批`)
    if (dark) await expectNotWhite(page.locator('[data-test=draft-group]').first(), '草稿分组')

    // 审批详情：元信息、diff、护栏与批准按钮
    await page.goto(`/approvals/${E2E_DRAFT_ID}`)
    await expect(page.locator('[data-test=diff-row] td')).toHaveText(['stock_on_hand', '3', '63'])
    await expect(page.locator('[data-test=approve]')).toBeEnabled()
    await expectNoHorizontalOverflow(page, `${theme} 审批详情`)

    // 售后：列表 + 打开详情
    await page.goto('/after-sales')
    await page.getByRole('button', { name: /退货退款.*顾客/ }).click()
    await expect(page.getByText('鞋跟处有明显划痕', { exact: false })).toBeVisible()
    await expectNoHorizontalOverflow(page, `${theme} 售后详情`)
    if (dark) await expectNotWhite(page.locator('.after-sales-view__detail'), '售后详情')

    // 顾客信号：未忽略（带原因输入）与已忽略两种卡片
    await page.goto('/customer-signals')
    await expect(page.locator('.signals-view__list li')).toHaveCount(2)
    await expect(page.getByRole('textbox', { name: '忽略原因' })).toBeVisible()
    await expectNoHorizontalOverflow(page, `${theme} 顾客信号`)

    // 商家记忆（运营分组）
    await page.goto('/memories')
    await expect(page.getByRole('heading', { level: 1, name: '商家记忆' })).toBeVisible()
    await expect(page.getByText('先致歉再给出处理时限', { exact: false })).toBeVisible()
    await expectNoHorizontalOverflow(page, `${theme} 商家记忆`)

    // 知识库（管理分组）：授权前只有令牌入口，授权后目录树 + 编辑器
    await page.goto('/knowledge-base')
    await expect(page.getByRole('button', { name: '进入后台' })).toBeVisible()
    await expect(page.locator('main')).toHaveCount(1)
    await expect(page.getByTestId('language-switcher')).toHaveCount(1)
    await expectNoHorizontalOverflow(page, `${theme} 知识库令牌入口`)
    if (dark) await expectNotWhite(page.locator('.admin-token-dialog'), '令牌入口')

    await page.getByLabel('管理员令牌').fill('mock-admin-token')
    await page.getByRole('button', { name: '进入后台' }).click()
    await expect(page.getByText('知识目录', { exact: true })).toBeVisible()
    await page.locator('[data-path="index/运营手册.md"]').click()
    const editor = page.getByRole('textbox', { name: 'index/运营手册.md 内容' })
    await expect(editor).toBeVisible()
    await expect(page.locator('main')).toHaveCount(1)
    await expect(page.getByTestId('language-switcher')).toHaveCount(1)
    await expectNoHorizontalOverflow(page, `${theme} 知识库`)
    if (dark) {
      await expectNotWhite(page.locator('.kb__workspace'), '知识库工作区')
      await expectNotWhite(editor, '文档编辑器')
      await expectNotWhite(page.getByTestId('create-document'), '工具栏按钮')
    }

    expect(errors).toEqual([])
  })
}
