import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import MerchantSwitcher from './MerchantSwitcher.vue'

describe('MerchantSwitcher', () => {
  it('选择商家时更新 v-model，且名称始终可见', async () => {
    const wrapper = mount(MerchantSwitcher, {
      props: {
        modelValue: 'Borough商家100',
        merchants: ['Borough商家100', 'Borough商家101'],
      },
    })

    await wrapper.get('button').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['Borough商家101'])
    expect(wrapper.get('button').text()).toContain('Borough商家100')
  })

  it('点击组件外部时关闭商家列表', async () => {
    const wrapper = mount(MerchantSwitcher, {
      attachTo: document.body,
      props: {
        modelValue: 'Borough商家100',
        merchants: ['Borough商家100', 'Borough商家101'],
      },
    })

    await wrapper.get('.merchant-switcher__trigger').trigger('click')
    expect(wrapper.find('.merchant-switcher__menu').exists()).toBe(true)

    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await nextTick()

    expect(wrapper.find('.merchant-switcher__menu').exists()).toBe(false)
    wrapper.unmount()
  })

  it('焦点离开组件后按 Escape 仍关闭列表并把焦点还给触发按钮', async () => {
    const outsideButton = document.createElement('button')
    document.body.append(outsideButton)
    const wrapper = mount(MerchantSwitcher, {
      attachTo: document.body,
      props: {
        modelValue: 'Borough商家100',
        merchants: ['Borough商家100', 'Borough商家101'],
      },
    })
    const trigger = wrapper.get<HTMLButtonElement>('.merchant-switcher__trigger')

    await trigger.trigger('click')
    outsideButton.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()

    expect(wrapper.find('.merchant-switcher__menu').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
    outsideButton.remove()
  })
})
