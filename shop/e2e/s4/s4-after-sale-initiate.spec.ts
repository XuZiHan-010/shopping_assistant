import { expect, test } from '@playwright/test'

const ORDER_ID = '00000000-0000-0000-0000-0000000054c1'

test('S4 顾客核对后确认售后，未勾选时不能提交', async ({ page }) => {
  await page.goto(`/borough-s4-e2e/orders/${ORDER_ID}`)
  await expect(page.getByTestId('identity')).toHaveText('访客')
  await page.getByRole('button', { name: '绑定演示顾客' }).click()
  await expect(page.getByRole('link', { name: '申请售后' })).toBeVisible()
  await page.getByRole('link', { name: '申请售后' }).click()
  await expect(page.getByRole('heading', { name: '售后服务' })).toBeVisible()
  await page.getByRole('button', { name: '预览申请' }).click()
  await expect(page.getByText('后端计算的预计可退金额：¥100.00')).toBeVisible()
  const submit = page.getByRole('button', { name: '确认提交' })
  await expect(submit).toBeDisabled()
  await page.getByRole('checkbox', { name: '我已核对申请信息' }).check()
  await submit.click()
  await expect(page.getByText('申请已提交。')).toBeVisible()
  await expect(page.getByRole('button', { name: new RegExp(`仅退款.*${ORDER_ID}`) })).toBeVisible()
  await page.getByRole('button', { name: new RegExp(`仅退款.*${ORDER_ID}`) }).click()
  await expect(page.getByRole('heading', { name: '售后详情' })).toBeVisible()
  await expect(page.getByRole('region', { name: '售后详情' })).toContainText('待商家处理')
  await page.setViewportSize({ width: 375, height: 812 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})
