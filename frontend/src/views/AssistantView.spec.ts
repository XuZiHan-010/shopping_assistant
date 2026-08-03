import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import ConversationColumn from '@/components/chat/ConversationColumn.vue'
import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import { useChatStore } from '@/stores/chat'
import AssistantView from './AssistantView.vue'

describe('AssistantView', () => {
  function mountView() {
    const pinia = createPinia()
    setActivePinia(pinia)
    return mount(AssistantView, {
      global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
  }

  it('为商家问题提供可聚焦的输入区', () => {
    const wrapper = mountView()

    expect(wrapper.find('textarea[aria-label="输入问题"]').exists()).toBe(true)
  })

  it('让页头与对话区分别成为 banner 和 main landmark', () => {
    const wrapper = mountView()
    const conversation = wrapper.findComponent(ConversationColumn)

    expect(wrapper.element.tagName).toBe('DIV')
    expect(wrapper.find(':scope > header').exists()).toBe(true)
    expect(conversation.element.tagName).toBe('MAIN')
  })

  it('提供直接跳到对话主内容的跳转链接', () => {
    const wrapper = mountView()

    expect(wrapper.get('.skip-link').attributes('href')).toBe('#main-content')
    expect(wrapper.findComponent(ConversationColumn).attributes('id')).toBe('main-content')
  })

  it('按主布局契约组合工作区、双侧栏、对话列和商家切换器', () => {
    const wrapper = mountView()

    expect(wrapper.find('[data-testid="workspace-grid"]').exists()).toBe(true)
    expect(wrapper.findAll('aside')).toHaveLength(2)
    expect(wrapper.findComponent(ConversationColumn).exists()).toBe(true)
    expect(wrapper.findComponent(MerchantSwitcher).exists()).toBe(true)
  })

  it('选择演示商家后更新顶栏中可见的商家名', async () => {
    const wrapper = mountView()

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')

    expect(wrapper.get('button[aria-label="切换当前演示商家"]').text()).toContain('Borough商家101')
  })

  it('重复选择当前商家时保留会话，切换到其他商家时才重置', async () => {
    const wrapper = mountView()
    const chatStore = useChatStore()
    chatStore.isEmptyConversation = false

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家100"]').trigger('click')
    expect(chatStore.isEmptyConversation).toBe(false)

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')
    expect(chatStore.isEmptyConversation).toBe(true)
  })
})
