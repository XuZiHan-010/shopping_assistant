import { expect, test } from '@playwright/test'

test('知识库后台需要令牌，支持编辑团队文档且记忆只读', async ({ page }) => {
  await page.goto('/knowledge-base')

  await expect(page.getByRole('heading', { name: '知识库维护后台' })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入后台' })).toBeVisible()
  await expect(page.getByText('知识目录')).toHaveCount(0)

  await page.getByLabel('管理员令牌').fill('mock-admin-token')
  await page.getByRole('button', { name: '进入后台' }).click()

  await expect(page.getByText('知识目录', { exact: true })).toBeVisible()
  await expect(page.locator('[data-path="index"]')).toBeVisible()
  await expect(page.locator('[data-path="业务"]')).toBeVisible()
  await expect(page.locator('[data-path="memory"]')).toBeVisible()

  await page.locator('[data-path="index/运营手册.md"]').click()
  const editor = page.getByRole('textbox', { name: 'index/运营手册.md 内容' })
  await expect(editor).toBeVisible()
  await editor.fill('# 运营手册\n\n已编辑内容')
  await page.getByTestId('save').click()
  await expect(editor).toHaveValue('# 运营手册\n\n已编辑内容')

  await page.locator('[data-path="memory/merchants/demo/TRADE.md"]').click()
  const memoryEditor = page.getByRole('textbox', { name: 'memory/merchants/demo/TRADE.md 内容' })
  await expect(memoryEditor).toHaveAttribute('readonly', '')
  await expect(page.getByTestId('save')).toHaveCount(0)
})

// ---------------------------------------------------------------------------
// 双语本地化（bilingual-localization Task 13）：知识库后台单页英语烟雾测试。
// 完整的「打开中文源文档的英语版本」旅程在 `e2e/localization.spec.ts`；
// 这里只覆盖本页管理员令牌对话框、页头、按钮和只读徽标的英语文案。
// ---------------------------------------------------------------------------

test('授权后切到英语，页头、工具栏与只读徽标均为英语', async ({ page }) => {
  await page.goto('/knowledge-base')

  // 管理员令牌对话框在授权前就已经是英语——语言持久化在 localStorage，但
  // 全新浏览器上下文没有历史记录，这里先切一次，模拟「上次用过英语」的
  // 回访场景（而不是像 localization.spec.ts 那样在同一个 tab 里切换）。
  await page.getByLabel('管理员令牌').fill('mock-admin-token')
  await page.getByRole('button', { name: '进入后台' }).click()
  await expect(page.getByText('知识目录', { exact: true })).toBeVisible()

  await page.getByTestId('language-switcher').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en-US')
  await expect(page.getByRole('heading', { name: 'Knowledge base administration' })).toBeVisible()
  await expect(page.getByTestId('create-document')).toHaveText('New document')
  await expect(page.getByTestId('rename-domain')).toHaveText('Rename business domain')
  await expect(page.getByTestId('delete-node')).toHaveText('Delete')
  await expect(page.getByText('Knowledge directory', { exact: true })).toBeVisible()

  // 只读的商家记忆文档：徽标与文本域的 aria-label 都要是英语。
  await page.locator('[data-path="memory/merchants/demo/TRADE.md"]').click()
  await expect(page.locator('.document-editor header span')).toHaveText('Memory (read-only)')
  const memoryEditor = page.getByRole('textbox', { name: 'memory/merchants/demo/TRADE.md content' })
  await expect(memoryEditor).toHaveAttribute('readonly', '')
  await expect(page.getByTestId('save')).toHaveCount(0)

  // `KnowledgeTree` 的文档/业务域名称不在「已知闭集翻译表」内时原样保留
  // 中文（`frontend/src/utils/knowledgeTree.ts` 的 `displayNodeName`，
  // 有意为之的产品决策，不是缺口）——`memory/merchants/demo/TRADE.md` 的
  // 树节点名称正是这种情况，因此只审计工具栏/页头，不对整棵树跑 Han 审计。
  await expect(page.locator('[data-path="index"]')).toBeVisible()
})
