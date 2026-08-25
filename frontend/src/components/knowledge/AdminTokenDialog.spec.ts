import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AdminTokenDialog from './AdminTokenDialog.vue'

describe('管理员令牌对话框', () => {
  it('作为可访问的管理员令牌对话框呈现', () => {
    const wrapper = mount(AdminTokenDialog)

    expect(wrapper.get('[role="dialog"]').attributes('aria-labelledby')).toBe('admin-token-title')
  })

  it('允许管理员页面提供自己的标题', () => {
    const wrapper = mount(AdminTokenDialog, { props: { title: 'Chat BI 运营看板' } })

    expect(wrapper.get('h1').text()).toBe('Chat BI 运营看板')
  })

  it('提交时仅向父级交出输入值，不自行持久化', async () => {
    const wrapper = mount(AdminTokenDialog)

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
    const wrapper = mount(AdminTokenDialog)

    expect(wrapper.find('[data-testid="use-viewer-token"]').exists()).toBe(false)
  })

  it('已配置时勾选后令牌以明文显示在输入框中', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mount(AdminTokenDialog)

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)

    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('text')
    expect((input.element as HTMLInputElement).value).toBe('public-viewer-token')
  })

  it('勾选后提交即以只读令牌进入，不需要手动输入', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mount(AdminTokenDialog)

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['public-viewer-token'])
  })

  it('取消勾选后清空输入框并恢复为密码框', async () => {
    vi.stubEnv('VITE_VIEWER_TOKEN', 'public-viewer-token')
    const wrapper = mount(AdminTokenDialog)

    await wrapper.get('[data-testid="use-viewer-token"]').setValue(true)
    await wrapper.get('[data-testid="use-viewer-token"]').setValue(false)

    const input = wrapper.get('input[data-testid="admin-token-input"]')
    expect(input.attributes('type')).toBe('password')
    expect((input.element as HTMLInputElement).value).toBe('')
  })
})
