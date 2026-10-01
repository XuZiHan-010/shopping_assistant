/**
 * 会话目录 + 移动端无横向溢出（`n2-conversations-and-feedback` Task 4，PRD §12.4 / M1）。
 *
 * 在 375px 宽度下走完一遍真实的会话目录流程：发起对话 → 目录出现 → 新建 → 打开历史 → 删除当前对话，
 * 每个状态都断言 `scrollWidth <= innerWidth`。后端是真实代码 + 真实 PostgreSQL，模型脚本化（零费用）：
 * 不含「围巾」的提问只得到固定问候。
 *
 * 页面内导航一律点链接：会话只在浏览器内存里，整页跳转会换成新的访客会话。
 */
import { expect, test, type Page } from '@playwright/test'

const SHOP = '/borough-s1-e2e'
// 一段没有空格的长串：用来确认长标题与长气泡在窄屏上换行或截断，而不是把页面撑宽。
const LONG_TOKEN = 'ORDER-REF-' + 'X'.repeat(90)

test.use({ viewport: { width: 375, height: 812 } })

async function expectNoHorizontalOverflow(page: Page, state: string) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  expect(scrollWidth, `${state}：页面宽 ${scrollWidth}px，视口 ${innerWidth}px`).toBeLessThanOrEqual(innerWidth)
}

function directory(page: Page) {
  return page.getByRole('dialog', { name: '动态' })
}

async function openHistory(page: Page) {
  await page.getByRole('button', { name: '动态' }).click()
  await directory(page).getByRole('tab', { name: '对话记录' }).click()
}

/** 发送一句并等到这一轮的回答气泡出现正文（`turn_complete` 已到）。 */
async function ask(page: Page, text: string) {
  const bubbles = page.locator('[aria-live="polite"] > li')
  const before = await bubbles.count()
  await page.getByRole('textbox', { name: '向智能助手提问' }).fill(text)
  await page.getByRole('button', { name: '发送' }).click()
  await expect(bubbles).toHaveCount(before + 2)
  await expect(bubbles.nth(before + 1)).not.toBeEmpty()
}

test('375px：会话目录新建、浏览、跳转、删除全程无横向溢出', async ({ page }) => {
  await page.goto(SHOP)
  await expect(page.getByTestId('identity')).toHaveText('访客')
  await page.getByRole('button', { name: '访客' }).click()
  await page.getByRole('group', { name: '访客' }).getByRole('button', { name: '绑定演示顾客' }).click()
  await expect(page.getByTestId('identity')).toHaveText('演示顾客')
  await expectNoHorizontalOverflow(page, '店铺首页')

  await expect(page.getByRole('navigation', { name: '店铺视图' }).getByRole('link', { name: '智能助手' })).toHaveAttribute('aria-current', 'page')
  await openHistory(page)
  await expect(directory(page).getByText('还没有对话记录。')).toBeVisible()
  await directory(page).getByRole('button', { name: '关闭' }).click()
  await expectNoHorizontalOverflow(page, '导购页空目录')

  // 第一段对话：带长串，检验气泡与目录标题的换行/截断。
  await ask(page, `你好 ${LONG_TOKEN}`)
  await openHistory(page)
  const firstEntry = directory(page).getByRole('listitem')
  await expect(firstEntry).toHaveCount(1)
  await expectNoHorizontalOverflow(page, '第一段对话结束')
  await directory(page).getByRole('button', { name: '关闭' }).click()

  // 新建：当前轮次清空，第二段对话成为目录里的第二条。
  await page.getByRole('button', { name: '新对话' }).click()
  await expect(page.locator('[aria-live="polite"] > li')).toHaveCount(0)
  await ask(page, '你好，第二段')
  await openHistory(page)
  await expect(directory(page).getByRole('listitem')).toHaveCount(2)
  await expectNoHorizontalOverflow(page, '第二段对话结束')

  // 跳转历史：打开第一段，看到当时的提问。
  const firstTitle = directory(page).getByRole('button', { name: /^你好 ORDER-REF-/ })
  await firstTitle.click()
  await expect(page.locator('[aria-live="polite"]').getByText(LONG_TOKEN, { exact: false })).toBeVisible()
  await expectNoHorizontalOverflow(page, '打开历史对话')

  // 删除当前对话：目录少一条，界面回到新建态。
  await openHistory(page)
  await directory(page).getByRole('button', { name: /^删除：你好 ORDER-REF-/ }).click()
  await expect(directory(page).getByRole('listitem')).toHaveCount(1)
  await expect(page.locator('[aria-live="polite"] > li')).toHaveCount(0)
  await expectNoHorizontalOverflow(page, '删除当前对话后')
})
