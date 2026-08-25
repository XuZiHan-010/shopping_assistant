import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PromptDialog from './PromptDialog.vue'

describe('知识库命名对话框', () => {
  it('提交时携带输入值并清空输入框', async () => {
    const wrapper = mount(PromptDialog, {
      props: { title: '新建文档', label: '文档名称' },
    })

    await wrapper.get('input').setValue('订单履约口径.md')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['订单履约口径.md'])
  })

  it('空白输入不触发提交', async () => {
    const wrapper = mount(PromptDialog, {
      props: { title: '新建业务域', label: '业务域名称' },
    })

    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('点击取消触发 cancel 事件', async () => {
    const wrapper = mount(PromptDialog, {
      props: { title: '新建文档', label: '文档名称' },
    })

    await wrapper.get('[data-testid="cancel"]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('展示传入的错误信息且不清空输入', async () => {
    const wrapper = mount(PromptDialog, {
      props: { title: '新建文档', label: '文档名称', errorMessage: '同名文档已存在' },
    })
    await wrapper.get('input').setValue('已存在.md')

    expect(wrapper.text()).toContain('同名文档已存在')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('已存在.md')
  })

  it('提交中禁用提交按钮', () => {
    const wrapper = mount(PromptDialog, {
      props: { title: '新建文档', label: '文档名称', pending: true },
    })

    expect(wrapper.get('[data-testid="submit"]').attributes('disabled')).toBeDefined()
  })

  it('支持初始值，便于重命名场景预填当前名称', () => {
    const wrapper = mount(PromptDialog, {
      props: { title: '重命名业务域', label: '业务域名称', initialValue: '客服' },
    })

    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('客服')
  })
})
