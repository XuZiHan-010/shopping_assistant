import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ConfirmDeleteDialog from './ConfirmDeleteDialog.vue'

describe('知识库删除确认对话框', () => {
  it('展示待删除节点的名称与路径', () => {
    const wrapper = mount(ConfirmDeleteDialog, {
      props: { name: '客服', path: '业务/客服' },
    })

    expect(wrapper.text()).toContain('客服')
    expect(wrapper.text()).toContain('业务/客服')
  })

  it('业务域删除时提示将级联删除全部文档', () => {
    const wrapper = mount(ConfirmDeleteDialog, {
      props: { name: '客服', path: '业务/客服', isDomain: true },
    })

    expect(wrapper.text()).toContain('级联删除')
  })

  it('点击确认触发 confirm 事件', async () => {
    const wrapper = mount(ConfirmDeleteDialog, {
      props: { name: '运营手册.md', path: 'index/运营手册.md' },
    })

    await wrapper.get('[data-testid="confirm"]').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('点击取消触发 cancel 事件', async () => {
    const wrapper = mount(ConfirmDeleteDialog, {
      props: { name: '运营手册.md', path: 'index/运营手册.md' },
    })

    await wrapper.get('[data-testid="cancel"]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('展示传入的错误信息', () => {
    const wrapper = mount(ConfirmDeleteDialog, {
      props: { name: 'a.md', path: 'index/a.md', errorMessage: '文档已被其他维护者更新' },
    })

    expect(wrapper.text()).toContain('文档已被其他维护者更新')
  })

  it('处理中禁用确认按钮', () => {
    const wrapper = mount(ConfirmDeleteDialog, {
      props: { name: 'a.md', path: 'index/a.md', pending: true },
    })

    expect(wrapper.get('[data-testid="confirm"]').attributes('disabled')).toBeDefined()
  })
})
