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
  // 默认按「未配置只读令牌」跑，不受本机 .env 影响；需要只读入口的用例各自覆盖。
  vi.stubEnv('VITE_VIEWER_TOKEN', '')
})

afterEach(() => {
  vi.unstubAllEnvs()
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
  it('未配置只读令牌时不显示该入口，输入框为空的密码框', () => {
    const wrapper = mountDialog()

    expect(wrapper.find('[data-testid="use-viewer-token"]').exists()).toBe(false)
    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('password')
    expect((input.element as HTMLInputElement).value).toBe('')
    expect(wrapper.text()).toContain('请输入管理员令牌后继续。')
  })

  it('已配置时默认勾选，令牌以明文预填在只读输入框中', () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    const toggle = wrapper.get('[data-testid="use-viewer-token"]')
    expect((toggle.element as HTMLInputElement).checked).toBe(true)
    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('text')
    expect(input.attributes('readonly')).toBeDefined()
    expect((input.element as HTMLInputElement).value).toBe('public-viewer-token')
  })

  it('已配置时说明文案告诉访客默认只读、取消勾选可输入管理员令牌', () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    expect(wrapper.text()).toContain('默认以只读令牌浏览')
    expect(wrapper.text()).not.toContain('请输入管理员令牌后继续。')
  })

  it('不做任何操作直接提交即以只读令牌进入', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['public-viewer-token'])
  })

  it('取消勾选后清空输入框并恢复为可输入的密码框', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(false)

    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('readonly')).toBeUndefined()
    expect((input.element as HTMLInputElement).value).toBe('')
  })

  it('取消勾选后可以输入管理员令牌提交', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(false)
    await wrapper.get('input[data-testid="admin-token-input"]').setValue('secret-token')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['secret-token'])
  })

  it('重新勾选后恢复为只读令牌', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mountDialog()

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(false)
    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)

    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect((input.element as HTMLInputElement).value).toBe('public-viewer-token')
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
    expect(wrapper.text()).toContain('Read-only browsing is selected by default.')
  })
})
