import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatComposer from './ChatComposer.vue'

/**
 * happy-dom 不做真实排版，scrollHeight 恒为 0——自适应高度在这里只能靠桩来测。
 * 桩按「内容有多少行」返回高度，从而能同时验证「变长会长高」和「变短会缩回」。
 */
function stubAutoHeight(textarea: HTMLTextAreaElement): void {
  Object.defineProperty(textarea, 'scrollHeight', {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      // height 被置成 'auto' 时才量内容；否则回报当前已设定的高度。
      if (this.style.height !== 'auto' && this.style.height !== '') {
        return Number.parseFloat(this.style.height)
      }
      return 24 * this.value.split('\n').length
    },
  })
}

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

  it('输入框随内容长高，内容变短时缩回，提交清空后回到单行', async () => {
    const wrapper = mount(ChatComposer)
    const textarea = wrapper.get('textarea')
    stubAutoHeight(textarea.element as HTMLTextAreaElement)

    await textarea.setValue('第一行\n第二行\n第三行')
    await flushPromises()
    expect(textarea.element.style.height).toBe('72px')

    await textarea.setValue('第一行\n第二行')
    await flushPromises()
    // 若忘了先把 height 归零再量，这里会停在 72px——只长不缩。
    expect(textarea.element.style.height).toBe('48px')

    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(textarea.element.style.height).toBe('24px')
  })

  it('在附件功能尚未实现时明确禁用附件控件', () => {
    const wrapper = mount(ChatComposer)

    expect(wrapper.get('.chat-composer__attachment').attributes('disabled')).toBeDefined()
  })
})
