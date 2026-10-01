import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import PreferencesPanel from './PreferencesPanel.vue'

const root = document.documentElement

// 每个用例挂载的面板都在 document 上注册了 keydown 监听；统一在 afterEach 卸载，
// 不让监听器泄漏到后续用例。
const mounted: Array<{ unmount: () => void }> = []

function mountPanel() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(PreferencesPanel, {
    attachTo: document.body,
    global: { plugins: [pinia, i18n] },
  })
  mounted.push(wrapper)
  return { wrapper }
}

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  localStorage.clear()
  delete root.dataset.theme
  delete root.dataset.size
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('PreferencesPanel 偏好设置', () => {
  it('是带标题的对话框，四项偏好齐全', () => {
    const { wrapper } = mountPanel()

    const dialog = wrapper.get('[role="dialog"]')
    const titleId = dialog.attributes('aria-labelledby')
    expect(titleId).toBeTruthy()
    expect(wrapper.get(`#${titleId}`).text()).toBe('偏好设置')
    expect(wrapper.text()).toContain('主题')
    expect(wrapper.text()).toContain('语言')
    expect(wrapper.text()).toContain('界面字号')
    expect(wrapper.text()).toContain('助手快捷键')
  })

  it.each([
    ['system', 'system'],
    ['light', 'light'],
    ['dark', 'dark'],
  ])('主题选 %s 写入 <html data-theme="%s">', async (value, expected) => {
    const { wrapper } = mountPanel()

    await wrapper.get('select[name="theme"]').setValue(value)

    expect(root.dataset.theme).toBe(expected)
  })

  it('主题三档都有选项：跟随系统、浅色、深色', () => {
    const { wrapper } = mountPanel()

    const options = wrapper.findAll('select[name="theme"] option')
    expect(options.map((option) => option.attributes('value'))).toEqual(['system', 'light', 'dark'])
    expect(options.map((option) => option.text())).toEqual(['跟随系统', '浅色', '深色'])
  })

  it.each(['sm', 'md', 'lg'])('字号选 %s 写入 data-size', async (size) => {
    const { wrapper } = mountPanel()

    await wrapper.get('select[name="size"]').setValue(size)

    expect(root.dataset.size).toBe(size)
  })

  it('语言切换走 locale store', async () => {
    const { wrapper } = mountPanel()
    const locale = useLocaleStore()
    const setLocale = vi.spyOn(locale, 'setLocale')

    await wrapper.get('select[name="language"]').setValue('en-US')

    expect(setLocale).toHaveBeenCalledWith('en-US')
  })

  it('语言切换后面板文案随之切换', async () => {
    const { wrapper } = mountPanel()

    await wrapper.get('select[name="language"]').setValue('en-US')

    expect(i18n.global.locale.value).toBe('en-US')
    expect(wrapper.text()).toContain('Preferences')
  })

  it('快捷键说明显示 Ctrl/⌘ + J', () => {
    const { wrapper } = mountPanel()

    const keys = wrapper.findAll('kbd').map((kbd) => kbd.text())
    expect(keys.at(-1)).toBe('J')
    expect(['Ctrl', '⌘']).toContain(keys[0])
  })

  it('点关闭按钮或按 Escape 都发出 close', async () => {
    const { wrapper } = mountPanel()

    await wrapper.get('[data-testid="preferences-close"]').trigger('click')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(wrapper.emitted('close')).toHaveLength(2)
  })

  it('localStorage 抛错时面板照常渲染、选择照常生效', async () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const { wrapper } = mountPanel()

    await wrapper.get('select[name="theme"]').setValue('dark')

    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(root.dataset.theme).toBe('dark')
  })

  it('挂载即把焦点移进对话框', () => {
    const { wrapper } = mountPanel()

    expect(wrapper.get('[role="dialog"]').element.contains(document.activeElement)).toBe(true)
  })
})
