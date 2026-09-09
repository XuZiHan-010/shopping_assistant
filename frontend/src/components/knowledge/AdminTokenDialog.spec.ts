import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import AdminTokenDialog from './AdminTokenDialog.vue'

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(AdminTokenDialog, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('管理员令牌对话框', () => {
  it('作为可访问的管理员令牌对话框呈现', () => {
    const wrapper = mountDialog()

    expect(wrapper.get('[role="dialog"]').attributes('aria-labelledby')).toBe('admin-token-title')
  })

  it('允许管理员页面提供自己的标题', () => {
    const wrapper = mountDialog({ title: 'Chat BI 运营看板' })

    expect(wrapper.get('h1').text()).toBe('Chat BI 运营看板')
  })

  it('提交时仅向父级交出输入值，不自行持久化', async () => {
    const wrapper = mountDialog()

    await wrapper.get('input[type="password"]').setValue('secret-token')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['secret-token'])
    expect(localStorage.getItem('adminToken')).toBeNull()
  })
})

describe('只读令牌浏览', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('未配置只读令牌时不显示该入口', () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', '')
    const wrapper = mountDialog()

    expect(wrapper.find('[data-testid="use-viewer-token"]').exists()).toBe(false)
  })

  it('已配置时勾选后令牌以明文显示在输入框中', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)

    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('text')
    expect((input.element as HTMLInputElement).value).toBe('public-viewer-token')
  })

  it('勾选后提交即以只读令牌进入，不需要手动输入', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['public-viewer-token'])
  })

  it('取消勾选后清空输入框并恢复为密码框', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)
    await wrapper.get('[data-testid="use-viewer-token"]').setValue(false)

    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('password')
    expect((input.element as HTMLInputElement).value).toBe('')
  })
})

describe('en-US 下确定性文案为英文', () => {
  beforeEach(() => {
    useLocaleStore().setLocale('en-US')
  })

  it('默认标题、说明、标签与按钮均为英文', () => {
    const wrapper = mountDialog()

    expect(wrapper.get('h1').text()).toBe('Knowledge base administration')
    expect(wrapper.text()).toContain('Enter the admin token to continue.')
    expect(wrapper.get('label[for="admin-token"]').text()).toBe('Admin token')
    expect(wrapper.get('button[type="submit"]').text()).toBe('Enter administration')
  })

  it('显式传入的 title 优先于默认英文文案', () => {
    const wrapper = mountDialog({ title: 'Chat BI Dashboard' })

    expect(wrapper.get('h1').text()).toBe('Chat BI Dashboard')
  })

  it('只读令牌勾选项展示英文文案', () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    expect(wrapper.text()).toContain('Browse with the read-only token')
  })
})
