import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { useChatStore } from '@/stores/chat'

import ConversationDrawer from './ConversationDrawer.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  // 每个用例都从中文默认语言出发，避免上一条用例切到英文后残留。
  i18n.global.locale.value = 'zh-CN'
})

describe('ConversationDrawer', () => {
  it('列出已有会话，删除需要二次确认', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    expect(wrapper.findAll('[data-testid="conversation-item"]')).toHaveLength(1)

    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    // 第一次点击只进入确认态，会话不能就这么没了——删除无法撤销。
    expect(store.conversations).toHaveLength(1)

    await wrapper.get('[data-testid="conversation-delete-confirm"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.conversations).toHaveLength(0)
  })

  it('确认前可以取消，会话保留', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await wrapper.get('[data-testid="conversation-delete-cancel"]').trigger('click')

    expect(store.conversations).toHaveLength(1)
    expect(wrapper.find('[data-testid="conversation-delete-confirm"]').exists()).toBe(false)
  })

  it('删除失败时给出可见提示，而不是留一条未处理的 Promise 拒绝', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    setChatTransport(async () => {
      throw new Error('网络中断')
    })

    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await wrapper.get('[data-testid="conversation-delete-confirm"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('删除失败')
    expect(store.conversations).toHaveLength(1)
  })

  it('点击会话把历史消息载入当前会话', async () => {
    const store = useChatStore()
    await store.submitMessage('昨天总 GMV 是多少？')
    await store.loadConversations()
    const conversationId = store.conversations[0].id
    store.reset()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    await wrapper.get('[data-testid="conversation-open"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.sessionId).toBe(conversationId)
    expect(store.messages).toHaveLength(2)
    expect(store.messages[0].text).toBe('昨天总 GMV 是多少？')
    expect(store.messages[0].status).toBe('complete')
  })

  it('open 为 false 时不渲染内容', () => {
    const wrapper = mount(ConversationDrawer, { props: { open: false } })

    expect(wrapper.find('[data-testid="conversation-item"]').exists()).toBe(false)
  })

  it('Escape 关闭抽屉', async () => {
    const wrapper = mount(ConversationDrawer, { props: { open: true } })

    await wrapper.get('[data-testid="drawer-panel"]').trigger('keydown', { key: 'Escape' })

    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('英文模式下标题、空态、关闭按钮 aria-label 均为英文，且不残留中文', () => {
    i18n.global.locale.value = 'en-US'

    const wrapper = mount(ConversationDrawer, { props: { open: true } })

    expect(wrapper.get('h2').text()).toBe('Conversation history')
    expect(wrapper.get('[data-testid="drawer-panel"]').attributes('aria-label')).toBe(
      'Conversation history',
    )
    expect(wrapper.find('.conversation-drawer__empty').text()).toBe(
      'No conversation history yet. Once you ask a question, it will show up here for you to revisit.',
    )
    expect(wrapper.get('header button').attributes('aria-label')).toBe(
      'Close conversation history',
    )
    expect(wrapper.text()).not.toMatch(/[一-鿿]/)
  })

  it('英文模式下删除相关按钮文案和 aria-label 均为英文', async () => {
    i18n.global.locale.value = 'en-US'
    const store = useChatStore()
    await store.submitMessage('hello')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    const conversationTitle = store.conversations[0].title

    expect(
      wrapper.get('[data-testid="conversation-delete"]').attributes('aria-label'),
    ).toBe(`Delete conversation ${conversationTitle}`)

    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')

    expect(wrapper.get('[data-testid="conversation-delete-confirm"]').text()).toBe(
      'Confirm delete',
    )
    expect(
      wrapper.get('[data-testid="conversation-delete-confirm"]').attributes('aria-label'),
    ).toBe(`Confirm deleting conversation ${conversationTitle}`)
    expect(wrapper.get('[data-testid="conversation-delete-cancel"]').text()).toBe('Cancel')
    expect(
      wrapper.get('[data-testid="conversation-delete-cancel"]').attributes('aria-label'),
    ).toBe('Cancel delete')
  })

  it('英文模式下删除失败提示为英文', async () => {
    i18n.global.locale.value = 'en-US'
    const store = useChatStore()
    await store.submitMessage('hello')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    setChatTransport(async () => {
      throw new Error('network down')
    })

    await wrapper.get('[data-testid="conversation-delete"]').trigger('click')
    await wrapper.get('[data-testid="conversation-delete-confirm"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('Delete failed. Please try again later.')
  })

  it('会话时间戳按当前 locale 本地化，而不是固定 zh-CN', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()
    store.conversations[0].updatedAt = '2026-08-31T12:30:00Z'

    i18n.global.locale.value = 'en-US'
    const wrapper = mount(ConversationDrawer, { props: { open: true } })

    expect(wrapper.get('.conversation-drawer__time').text()).toContain('Aug')
  })
})

describe('ConversationDrawer · 历史重试入口（Task 10B 缺口收尾）', () => {
  it('localizationDegraded 为 false 时不显示重试翻译入口', async () => {
    const store = useChatStore()
    await store.submitMessage('你好')
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })

    expect(wrapper.find('[data-testid="retry-translation"]').exists()).toBe(false)
  })

  it('会话列表降级时显示重试翻译入口，点击后重新拉取，成功后隐藏', async () => {
    const store = useChatStore()
    let call = 0
    setChatTransport(async (request) => {
      if (request.path.startsWith('/api/conversations') && request.method === 'GET') {
        call += 1
        return Response.json({
          items: [{ id: 'c1', title: call === 1 ? '[占位]' : '真实标题', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' }],
          limit: 20,
          offset: 0,
          localization_degraded: call === 1,
          localization_degraded_reason: call === 1 ? '翻译预算已用尽' : null,
        })
      }
      throw new Error(`未预期的请求：${request.path}`)
    })

    await store.loadConversations()
    expect(store.conversationsLocalizationDegraded).toBe(true)

    const wrapper = mount(ConversationDrawer, { props: { open: true } })
    expect(wrapper.find('[data-testid="retry-translation"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('部分会话标题翻译未完成')

    await wrapper.get('[data-testid="retry-translation"]').trigger('click')
    await flushPromises()

    expect(call).toBe(2)
    expect(store.conversationsLocalizationDegraded).toBe(false)
    expect(wrapper.find('[data-testid="retry-translation"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('真实标题')
  })

  it('英文模式下重试翻译入口文案与提示均为英文', async () => {
    i18n.global.locale.value = 'en-US'
    const store = useChatStore()
    setChatTransport(async () =>
      Response.json({
        items: [],
        limit: 20,
        offset: 0,
        localization_degraded: true,
        localization_degraded_reason: 'Translation budget exhausted',
      }),
    )
    await store.loadConversations()

    const wrapper = mount(ConversationDrawer, { props: { open: true } })

    expect(wrapper.get('[data-testid="retry-translation"]').text()).toBe('Retry translation')
    expect(wrapper.get('[data-testid="retry-translation"]').attributes('aria-label')).toBe(
      'Retry translating conversation titles',
    )
    expect(wrapper.text()).toContain('have not finished translating')
  })
})
