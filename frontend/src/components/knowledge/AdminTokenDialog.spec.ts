import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AdminTokenDialog from './AdminTokenDialog.vue'

describe('管理员令牌对话框', () => {
  it('提交时仅向父级交出输入值，不自行持久化', async () => {
    const wrapper = mount(AdminTokenDialog)

    await wrapper.get('input').setValue('secret-token')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['secret-token'])
    expect(localStorage.getItem('adminToken')).toBeNull()
  })
})
