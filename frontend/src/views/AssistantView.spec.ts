import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport, type TransportRequest } from '@/api/transport'
import ConversationColumn from '@/components/chat/ConversationColumn.vue'
import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import { useAppError } from '@/composables/useAppError'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage } from '@/types/chat'
import AssistantView from './AssistantView.vue'

describe('AssistantView', () => {
  beforeEach(() => {
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    sessionStorage.clear()
    // useAppError 是模块级单例，不清会把上一条断言的提示带进下一个用例。
    useAppError().clearError()
  })

  /**
   * 商家名不再是硬编码常量，而是挂载后由 Auth Store 异步取回的（F2 Task 9）。
   * 断言商家菜单之前必须把这次加载 flush 掉，否则菜单里一个选项都还没有。
   */
  async function mountView() {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(AssistantView, {
      // 焦点断言只有在真的挂进文档里才成立——游离节点上 focus() 是空操作。
      attachTo: document.body,
      global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    return wrapper
  }

  it('为商家问题提供可聚焦的输入区', async () => {
    const wrapper = await mountView()

    expect(wrapper.find('textarea[aria-label="输入问题"]').exists()).toBe(true)
  })

  it('让页头与对话区分别成为 banner 和 main landmark', async () => {
    const wrapper = await mountView()
    const conversation = wrapper.findComponent(ConversationColumn)

    expect(wrapper.element.tagName).toBe('DIV')
    expect(wrapper.find(':scope > header').exists()).toBe(true)
    expect(conversation.element.tagName).toBe('MAIN')
  })

  it('提供直接跳到对话主内容的跳转链接', async () => {
    const wrapper = await mountView()

    expect(wrapper.get('.skip-link').attributes('href')).toBe('#main-content')
    expect(wrapper.findComponent(ConversationColumn).attributes('id')).toBe('main-content')
  })

  it('按主布局契约组合工作区、双侧栏、对话列和商家切换器', async () => {
    const wrapper = await mountView()

    expect(wrapper.find('[data-testid="workspace-grid"]').exists()).toBe(true)
    expect(wrapper.findAll('aside')).toHaveLength(2)
    expect(wrapper.findComponent(ConversationColumn).exists()).toBe(true)
    expect(wrapper.findComponent(MerchantSwitcher).exists()).toBe(true)
  })

  it('挂载后展示来自演示商家端点的商家名，而不是硬编码常量', async () => {
    const wrapper = await mountView()

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')

    expect(wrapper.get('button[aria-label="切换当前演示商家"]').text()).toContain('Borough商家100')
    expect(wrapper.findAll('[data-merchant]')).toHaveLength(3)
  })

  it('选择演示商家后更新顶栏中可见的商家名', async () => {
    const wrapper = await mountView()

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')

    expect(wrapper.get('button[aria-label="切换当前演示商家"]').text()).toContain('Borough商家101')
  })

  it('刷新后按 sessionStorage 中的标识选回同一商家，且不落 Token', async () => {
    sessionStorage.setItem('selected_demo_merchant_key', 'merchant-102')

    const wrapper = await mountView()

    expect(wrapper.get('button[aria-label="切换当前演示商家"]').text()).toContain('Borough商家102')
    expect(JSON.stringify(sessionStorage)).not.toContain('demo-token')
  })

  /**
   * 只让某一条路径失败，其余照常。挂载时 restore() 与 loadConversations() 是
   * 并发的两条 fire-and-forget 调用，都失败的话谁最后写进全局提示区不确定，
   * 断言就会变成看运气。
   */
  function transportFailingOn(pathPrefix: string) {
    const healthy = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    return async (request: TransportRequest, signal: AbortSignal) => {
      if (request.path.startsWith(pathPrefix)) throw new Error('网络中断')
      return healthy(request, signal)
    }
  }

  it('商家列表加载失败时把提示送进全局错误区，而不是静默停在「加载中」', async () => {
    setChatTransport(transportFailingOn('/api/demo/merchants'))

    const wrapper = await mountView()

    expect(wrapper.get('button[aria-label="切换当前演示商家"]').text()).toContain('加载中')
    expect(useAppError().message.value).toContain('演示商家列表加载失败')
  })

  it('历史会话加载失败时提示用户，而不是把失败伪装成「暂无历史会话」', async () => {
    setChatTransport(transportFailingOn('/api/conversations'))

    await mountView()

    expect(useAppError().message.value).toContain('历史会话加载失败')
  })

  it('打开对话目录时重新拉取列表，并在关闭后把焦点还给触发按钮', async () => {
    const wrapper = await mountView()
    const chatStore = useChatStore()
    // 挂载那次拉取时还没有任何会话；新会话是在这之后才产生的。
    await chatStore.submitMessage('你好')

    const trigger = wrapper.get('button[aria-label="打开对话目录"]')
    await trigger.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('[data-testid="conversation-item"]')).toHaveLength(1)

    await wrapper.get('button[aria-label="关闭历史会话"]').trigger('click')

    expect(wrapper.find('[data-testid="drawer-panel"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it('切换商家会连同会话历史一起清掉，不把上一个商家的会话留在抽屉里', async () => {
    const wrapper = await mountView()
    const chatStore = useChatStore()
    await chatStore.submitMessage('你好')
    await chatStore.loadConversations()
    expect(chatStore.conversations).toHaveLength(1)

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')

    // 换商家等于换租户：当前对话和会话列表都必须归零。
    expect(chatStore.messages).toEqual([])
    expect(chatStore.conversations).toEqual([])
  })

  it('挂载时先恢复身份再拉会话列表，不并发', async () => {
    const order: string[] = []
    const healthy = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    setChatTransport(async (request: TransportRequest, signal: AbortSignal) => {
      order.push(request.path)
      return healthy(request, signal)
    })

    await mountView()

    // F3 起会话请求要带 Token，而 Token 是 restore() 才恢复出来的；
    // 并发发出去会赶在身份就绪之前到达服务端，直接 401。
    expect(order.indexOf('/api/demo/merchants')).toBeLessThan(order.indexOf('/api/conversations'))
  })

  it('重复选择当前商家时保留会话，切换到其他商家时才重置', async () => {
    const wrapper = await mountView()
    const chatStore = useChatStore()
    // isEmptyConversation 在 F2 起由 messages 派生（只读），这里改为直接
    // 灌入一条消息来模拟「已有会话」，而不是给只读的计算属性赋值。
    const seedMessage: ChatMessage = {
      localId: 'seed',
      clientRequestId: 'seed',
      role: 'user',
      text: '你好',
      createdAt: new Date().toISOString(),
      status: 'complete',
      steps: [],
    }
    chatStore.messages.push(seedMessage)

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家100"]').trigger('click')
    expect(chatStore.isEmptyConversation).toBe(false)

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')
    expect(chatStore.isEmptyConversation).toBe(true)
  })
})
