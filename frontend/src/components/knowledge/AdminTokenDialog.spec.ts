import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

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

    await wrapper.get('input').setValue('secret-token')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['secret-token'])
    expect(localStorage.getItem('adminToken')).toBeNull()
  })
})
