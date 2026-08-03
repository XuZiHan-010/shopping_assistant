import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'

describe('ChatComposer', () => {
  it('提交非空文本，并在提交后清空输入区', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('查看昨天 GMV')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([['查看昨天 GMV']])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('按 Enter 提交当前问题并清空输入区', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('查看昨天 GMV')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('submit')).toEqual([['查看昨天 GMV']])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('按 Shift + Enter 时保留换行且不提交', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('第一行')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: true })

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect((textarea.element as HTMLTextAreaElement).value).toBe('第一行')
  })

  it('输入法仍在组合文字时按 Enter 不提交', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')

    await textarea.setValue('测试')
    await textarea.trigger('keydown', { key: 'Enter', isComposing: true })

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect((textarea.element as HTMLTextAreaElement).value).toBe('测试')
  })

  it('在附件功能尚未实现时明确禁用附件控件', () => {
    const wrapper = mount(ChatComposer)

    expect(wrapper.get('.chat-composer__attachment').attributes('disabled')).toBeDefined()
  })
})
