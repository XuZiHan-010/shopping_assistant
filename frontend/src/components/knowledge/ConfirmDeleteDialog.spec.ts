import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import ConfirmDeleteDialog from './ConfirmDeleteDialog.vue'

function mountDialog(props: Record<string, unknown>) {
  return mount(ConfirmDeleteDialog, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('知识库删除确认对话框', () => {
  it('展示待删除节点的名称与路径', () => {
    const wrapper = mountDialog({ name: '客服', path: '业务/客服' })

    expect(wrapper.text()).toContain('客服')
    expect(wrapper.text()).toContain('业务/客服')
  })

  it('业务域删除时提示将级联删除全部文档', () => {
    const wrapper = mountDialog({ name: '客服', path: '业务/客服', isDomain: true })

    expect(wrapper.text()).toContain('级联删除')
  })

  it('点击确认触发 confirm 事件', async () => {
    const wrapper = mountDialog({ name: '运营手册.md', path: 'index/运营手册.md' })

    await wrapper.get('[data-testid="confirm"]').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('点击取消触发 cancel 事件', async () => {
    const wrapper = mountDialog({ name: '运营手册.md', path: 'index/运营手册.md' })

    await wrapper.get('[data-testid="cancel"]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('展示传入的错误信息', () => {
    const wrapper = mountDialog({
      name: 'a.md',
      path: 'index/a.md',
      errorMessage: '文档已被其他维护者更新',
    })

    expect(wrapper.text()).toContain('文档已被其他维护者更新')
  })

  it('处理中禁用确认按钮', () => {
    const wrapper = mountDialog({ name: 'a.md', path: 'index/a.md', pending: true })

    expect(wrapper.get('[data-testid="confirm"]').attributes('disabled')).toBeDefined()
  })
})

describe('en-US 下确定性文案为英文', () => {
  beforeEach(() => {
    useLocaleStore().setLocale('en-US')
  })

  it('标题、警告与按钮均为英文，业务名称/路径原样展示', () => {
    const wrapper = mountDialog({ name: '客服', path: '业务/客服' })

    expect(wrapper.get('h2').text()).toBe('Delete knowledge node')
    expect(wrapper.text()).toContain('This document will be deleted')
    expect(wrapper.get('[data-testid="cancel"]').text()).toBe('Cancel')
    expect(wrapper.get('[data-testid="confirm"]').text()).toBe('Confirm delete')
    expect(wrapper.text()).toContain('客服')
    expect(wrapper.text()).toContain('业务/客服')
  })

  it('业务域删除时展示英文级联删除警告', () => {
    const wrapper = mountDialog({ name: '客服', path: '业务/客服', isDomain: true })

    expect(wrapper.text()).toContain('cascade-deleted')
  })

  it('处理中态展示英文文案', () => {
    const wrapper = mountDialog({ name: 'a.md', path: 'index/a.md', pending: true })

    expect(wrapper.get('[data-testid="confirm"]').text()).toBe('Deleting…')
  })
})
