import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import ChatComposer from './ChatComposer.vue'

function mountComposer() {
  return mount(ChatComposer, { global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

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
    const wrapper = mountComposer()
    const textarea = wrapper.get('textarea')

    await textarea.setValue('查看昨天 GMV')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([['查看昨天 GMV']])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('按 Enter 提交当前问题并清空输入区', async () => {
    const wrapper = mountComposer()
    const textarea = wrapper.get('textarea')

    await textarea.setValue('查看昨天 GMV')
    await textarea.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('submit')).toEqual([['查看昨天 GMV']])
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('按 Shift + Enter 时保留换行且不提交', async () => {
    const wrapper = mountComposer()
    const textarea = wrapper.get('textarea')

    await textarea.setValue('第一行')
    await textarea.trigger('keydown', { key: 'Enter', shiftKey: true })

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect((textarea.element as HTMLTextAreaElement).value).toBe('第一行')
  })

  it('输入法仍在组合文字时按 Enter 不提交', async () => {
    const wrapper = mountComposer()
    const textarea = wrapper.get('textarea')

    await textarea.setValue('测试')
    await textarea.trigger('keydown', { key: 'Enter', isComposing: true })

    expect(wrapper.emitted('submit')).toBeUndefined()
    expect((textarea.element as HTMLTextAreaElement).value).toBe('测试')
  })

  it('输入框随内容长高，内容变短时缩回，提交清空后回到单行', async () => {
    const wrapper = mountComposer()
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

  it('附件控件可用并唤起隐藏的文件选择框', async () => {
    const wrapper = mountComposer()
    const picker = wrapper.get('input[type="file"]')
    const click = vi.spyOn(picker.element as HTMLInputElement, 'click')

    expect(wrapper.get('.chat-composer__attachment').attributes('disabled')).toBeUndefined()
    await wrapper.get('.chat-composer__attachment').trigger('click')
    expect(click).toHaveBeenCalledOnce()
  })

  it('en-US 下输入区、按钮和提示文案均为英文', () => {
    useLocaleStore().setLocale('en-US')
    const wrapper = mountComposer()

    expect(wrapper.get('textarea').attributes('aria-label')).toBe('Ask a question')
    expect(wrapper.get('textarea').attributes('placeholder')).toBe('Ask a business question…')
    expect(wrapper.get('.chat-composer__attachment').attributes('aria-label')).toBe(
      'Choose attachment',
    )
    expect(wrapper.get('.chat-composer__send').attributes('aria-label')).toBe('Send question')
    expect(wrapper.text()).toContain('Enter to send')
    expect(wrapper.text()).not.toMatch(/[一-龥]/)
  })
})
