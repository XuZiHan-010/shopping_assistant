import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { useChatStore } from '@/stores/chat'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'
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

  it('第一轮仍在进行时收到重试请求，用户能看到「仍在处理」的提示而不是被静默丢弃', async () => {
    // 复现 retryMessage 的重入守卫场景（Task 6）：第一轮还没结束时再收到一次
    // retry，Store 层会拒绝（返回 false）。这里验证的不是「Store 被调用了」，
    // 而是用户在界面上真的看得到反馈——否则将来有人把 @retry="retry" 改回
    // @retry="chatStore.retryMessage"，返回值被静默丢弃，TypeScript 不会报错，
    // 其余测试也不会变红，用户点重试却再也看不到任何提示。
    setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    const pending = store.submitMessage('你好')
    await new Promise((resolve) => setTimeout(resolve, 10))

    const localId = store.messages[1].localId
    expect(store.messages[1].status).not.toBe('complete')

    const assistantMessage = wrapper
      .findAllComponents(ChatMessage)
      .find((component) => component.props('message').localId === localId)
    expect(assistantMessage).toBeTruthy()

    assistantMessage!.vm.$emit('retry', localId)
    await flushPromises()

    expect(wrapper.text()).toContain('仍在处理中')

    // 收尾：主动取消第一轮，避免真的等它按 stepDelayMs 跑完（会拖慢测试）。
    store.cancelMessage(localId)
    await pending
  })
})
