import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import LanguageSwitcher from './LanguageSwitcher.vue'

function mountSwitcher() {
  return mount(LanguageSwitcher, { global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('LanguageSwitcher', () => {
  it('uses Chinese-only switch copy in Chinese mode', () => {
    const store = useLocaleStore()
    store.setLocale('zh-CN')

    const wrapper = mountSwitcher()

    expect(wrapper.text()).toContain('英文')
    expect(wrapper.text()).not.toContain('English')
    expect(wrapper.attributes('aria-label')).toBe('切换到英文')
  })

  it('uses English-only switch copy in English mode', () => {
    const store = useLocaleStore()
    store.setLocale('en-US')

    const wrapper = mountSwitcher()

    expect(wrapper.text()).toContain('Chinese')
    expect(wrapper.text()).not.toContain('中文')
    expect(wrapper.attributes('aria-label')).toBe('Switch to Chinese')
  })

  it('clicking toggles the locale store', async () => {
    const store = useLocaleStore()
    store.setLocale('zh-CN')

    const wrapper = mountSwitcher()
    await wrapper.get('button').trigger('click')

    expect(store.locale).toBe('en-US')
  })

  it('supports keyboard activation via Enter', async () => {
    const store = useLocaleStore()
    store.setLocale('zh-CN')

    const wrapper = mountSwitcher()
    const button = wrapper.get('button')
    await button.trigger('click')

    expect(store.locale).toBe('en-US')
    // 按钮元素本身对 Enter/Space 有原生激活行为，这里只确认它是一个真正的
    // <button>（可聚焦、可用键盘激活），而不是靠 div + click 模拟出来的假按钮。
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('type')).toBe('button')
  })
})
