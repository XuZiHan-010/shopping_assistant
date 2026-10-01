import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { LocaleProvider } from '@/i18n/LocaleProvider'
import { PREFS_KEY } from './preferences'
import { PreferencesPopover } from './PreferencesPopover'

const refresh = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))

afterEach(() => {
  localStorage.clear()
  document.cookie = 'shop_locale=; Path=/; Max-Age=0'
  delete document.documentElement.dataset.theme
  delete document.documentElement.dataset.size
  refresh.mockReset()
})

it('主题与字号立即生效并保存，Escape 关闭后焦点回到齿轮', async () => {
  const user = userEvent.setup()
  render(<LocaleProvider><PreferencesPopover /></LocaleProvider>)
  const trigger = screen.getByRole('button', { name: '偏好设置' })
  await user.click(trigger)
  const dialog = screen.getByRole('dialog', { name: '偏好设置' })
  await user.click(within(dialog).getByRole('button', { name: '深色' }))
  await user.click(within(dialog).getByRole('button', { name: '大' }))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(document.documentElement.dataset.size).toBe('lg')
  expect(JSON.parse(localStorage.getItem(PREFS_KEY)!)).toEqual({ theme: 'dark', size: 'lg' })
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(trigger).toHaveFocus()
})

it('选择 English 写入非身份 cookie 并刷新服务端页面', async () => {
  const user = userEvent.setup()
  render(<LocaleProvider><PreferencesPopover /></LocaleProvider>)
  await user.click(screen.getByRole('button', { name: '偏好设置' }))
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'English' }))
  expect(document.cookie).toContain('shop_locale=en-US')
  expect(document.documentElement.lang).toBe('en-US')
  expect(refresh).toHaveBeenCalledOnce()
  expect(screen.getByRole('dialog', { name: 'Preferences' })).toBeInTheDocument()
})
