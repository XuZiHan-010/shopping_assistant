/**
 * v2 运营助手 + 会话目录，移动端无横向溢出（`n2-conversations-and-feedback` Task 4B，PRD §12.4 / M1）。
 *
 * 真实后端 + 真实 PostgreSQL + 脚本化模型（零 LLM 费用），与 S3 验收共用一次播种。
 * **本用例不得改动库存或草稿**：Playwright 按文件名顺序执行，它先于 S3 闭环运行，
 * 而 S3 要求起点「暂无待批准草稿」。所以简报预填的「起草」问题只核对、不发送，
 * 对话只用脚本化模型的问候分支（不含「起草」「批准」）。
 */
import { expect, test, type ConsoleMessage, type Page } from '@playwright/test'

const PRODUCT = 'S3 验收商品'
// 没有空格的长串：确认长标题与长气泡在窄屏上折行或截断，而不是把页面撑宽。
const LONG_TOKEN = 'ORDER-REF-' + 'X'.repeat(90)

test.use({ viewport: { width: 375, height: 812 } })

async function expectNoHorizontalOverflow(page: Page, state: string) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }))
  expect(
    scrollWidth,
    `${state}：页面宽 ${scrollWidth}px，视口 ${innerWidth}px`,
  ).toBeLessThanOrEqual(innerWidth)
}

function directory(page: Page) {
  return page.getByRole('region', { name: '历史对话' })
}

function bubbles(page: Page) {
  return page.locator('.ops-view__bubble')
}

/** 发送一句并等到这一轮的回答气泡出现正文（`turn_complete` 已到）。 */
async function ask(page: Page, text: string) {
  const before = await bubbles(page).count()
  await page.getByRole('textbox', { name: '向运营助手提问' }).fill(text)
  await page.getByRole('button', { name: '发送' }).click()
  await expect(bubbles(page)).toHaveCount(before + 2)
  await expect(bubbles(page).nth(before + 1)).not.toBeEmpty()
}

test('375px：简报预填 → 运营助手对话 → 新建 / 浏览 / 跳转 / 删除，全程无横向溢出', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('console', (message: ConsoleMessage) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))

  // 今日简报：条目动作只预填并跳转，不代为发送。
  await page.goto('/today')
  await expect(page.getByRole('heading', { name: '今日简报' })).toBeVisible()
  await expectNoHorizontalOverflow(page, '今日简报')
  const action = page.locator('[data-test=next-action]').filter({ hasText: PRODUCT }).first()
  const prompt = (await action.textContent())?.trim() ?? ''
  expect(prompt).not.toBe('')
  await action.click()
  await expect(page).toHaveURL(/\/ops-assistant$/)
  const input = page.getByRole('textbox', { name: '向运营助手提问' })
  await expect(input).toHaveValue(prompt)
  await expect(bubbles(page)).toHaveCount(0)
  await expect(page.getByText(/只能查看库存告警、起草补货草稿/)).toBeVisible()
  await expect(directory(page).getByText('还没有历史对话。')).toBeVisible()
  await expectNoHorizontalOverflow(page, '运营助手空目录')

  // 第一段对话（问候分支）：带长串，检验气泡与目录标题的换行/截断。
  await ask(page, `你好 ${LONG_TOKEN}`)
  await expect(directory(page).getByRole('listitem')).toHaveCount(1)
  await expectNoHorizontalOverflow(page, '第一段对话结束')

  // 新建：当前轮次清空，第二段对话成为目录里的第二条（最近活动在前）。
  await directory(page).getByRole('button', { name: '新建对话' }).click()
  await expect(bubbles(page)).toHaveCount(0)
  await ask(page, '你好，第二段')
  await expect(directory(page).getByRole('listitem')).toHaveCount(2)
  await expectNoHorizontalOverflow(page, '第二段对话结束')

  // 跳转历史：打开第一段，看到当时的提问。
  const first = directory(page).locator('[data-test=ops-conversation-open]').filter({
    hasText: 'ORDER-REF-',
  })
  await first.click()
  await expect(first).toHaveAttribute('aria-current', 'true')
  await expect(page.locator('.ops-view__log').getByText(LONG_TOKEN, { exact: false })).toBeVisible()
  await expectNoHorizontalOverflow(page, '打开历史对话')

  // 删除当前对话：目录少一条，界面回到新建态。
  await directory(page)
    .locator('[data-test=ops-conversation-item]')
    .filter({ hasText: 'ORDER-REF-' })
    .locator('[data-test=ops-conversation-delete]')
    .click()
  await expect(directory(page).getByRole('listitem')).toHaveCount(1)
  await expect(bubbles(page)).toHaveCount(0)
  await expectNoHorizontalOverflow(page, '删除当前对话后')

  expect(errors).toEqual([])
})
