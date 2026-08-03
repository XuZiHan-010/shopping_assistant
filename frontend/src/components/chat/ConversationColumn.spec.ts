import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { useChatStore } from '@/stores/chat'

import ChatComposer from './ChatComposer.vue'
import ConversationColumn from './ConversationColumn.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
})

describe('ConversationColumn', () => {
  it('组合独立的 ChatComposer 与可滚动消息区域', () => {
    const wrapper = mount(ConversationColumn)

    expect(wrapper.findComponent(ChatComposer).exists()).toBe(true)
    expect(wrapper.find('[data-testid="chat-list"]').exists()).toBe(true)
  })

  it('空会话时展示快速问题，点击即完成一轮问答', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    const quick = wrapper.get('[data-testid="quick-question"]')
    const text = quick.text()
    await quick.trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.messages[0].text).toBe(text)
    expect(store.messages[1].status).toBe('complete')
  })

  it('有消息后不再展示空状态', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    await store.submitMessage('你好')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="quick-question"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="chat-message"]')).toHaveLength(2)
  })
})
