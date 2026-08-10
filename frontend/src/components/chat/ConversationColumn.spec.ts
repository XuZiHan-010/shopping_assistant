import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { QUICK_QUESTIONS } from '@/constants/quickQuestions'
import { useChatStore } from '@/stores/chat'

import ChatComposer from './ChatComposer.vue'
import ChatMessage from './ChatMessage.vue'
import ConversationColumn from './ConversationColumn.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
})

/**
 * happy-dom 不做真实排版，滚动尺寸全是 0——只能把「内容有多高、视口有多高」桩出来。
 * scrollHeight 跟着消息条数长，clientHeight 固定，于是「贴底」与「翻上去了」这两
 * 种状态都能确定性地构造出来。
 */
function stubScrollMetrics(list: HTMLElement, messageCount: () => number): void {
  Object.defineProperty(list, 'clientHeight', { configurable: true, get: () => 100 })
  Object.defineProperty(list, 'scrollHeight', {
    configurable: true,
    get: () => 100 + messageCount() * 200,
  })
}

describe('ConversationColumn', () => {
  it('组合独立的 ChatComposer 与可滚动消息区域', () => {
    const wrapper = mount(ConversationColumn)

    expect(wrapper.findComponent(ChatComposer).exists()).toBe(true)
    expect(wrapper.find('[data-testid="chat-list"]').exists()).toBe(true)
  })

  it('空会话时展示四个分类快速问题，点击即完成一轮问答', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    const entries = wrapper.findAll('[data-testid="quick-question"]')
    expect(entries).toHaveLength(QUICK_QUESTIONS.length)
    // 按钮文案含分类眉标，所以断言问题本身要用数据源而不是按钮全文。
    expect(entries.map((entry) => entry.attributes('data-question'))).toEqual([
      '最近7天退货量趋势',
      '昨天总 GMV 是多少？',
      '查看最近订单明细',
      '我要货品上架，具体规则有吗？',
    ])
    expect(entries[0].text()).toContain(QUICK_QUESTIONS[0].category)
    expect(entries[0].text()).toContain(QUICK_QUESTIONS[0].question)

    await entries[0].trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.messages[0].text).toBe(QUICK_QUESTIONS[0].question)
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

  it('新消息到达时自动滚到底', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()
    const list = wrapper.get('[data-testid="chat-list"]').element as HTMLElement
    stubScrollMetrics(list, () => store.messages.length)

    await store.submitMessage('你好')
    await flushPromises()

    // 两条消息 → scrollHeight 500，视口 100，贴底即 scrollTop 500。
    expect(list.scrollTop).toBe(500)
  })

  it('用户向上翻看历史时不抢滚动，滚回底部后重新跟随', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()
    const list = wrapper.get('[data-testid="chat-list"]').element as HTMLElement
    stubScrollMetrics(list, () => store.messages.length)

    await store.submitMessage('你好')
    await flushPromises()

    // 用户往上翻：距底部 400px，远超 48px 阈值。
    list.scrollTop = 0
    await wrapper.get('[data-testid="chat-list"]').trigger('scroll')

    await store.submitMessage('昨天总 GMV 是多少？')
    await flushPromises()
    // 若无条件滚到底，这里会变成 900——用户会被从正在读的位置弹走。
    expect(list.scrollTop).toBe(0)

    // 用户自己滚回底部后，重新恢复跟随。
    list.scrollTop = 900
    await wrapper.get('[data-testid="chat-list"]').trigger('scroll')

    await store.submitMessage('我要货品上架，具体规则有吗？')
    await flushPromises()
    expect(list.scrollTop).toBe(1300)
  })

  it('演示数据的降级提示必须出现在回答卡片上（R7）', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    await store.submitMessage('我的商家资料是什么？')
    await wrapper.vm.$nextTick()

    // identity-profile fixture 的 analysis_sources 是 ['FALLBACK']、degraded 为 true——
    // B4 起 METRIC/DETAIL 已改为真实查询，IDENTITY 仍是唯一保留降级语义的场景。
    // 不显示的话，页面上的回答看起来和真实商家资料一模一样。
    expect(store.messages[1].answer?.quality.degraded).toBe(true)
    const notice = wrapper.get('[data-testid="degraded-notice"]')
    expect(notice.text()).toContain('演示数据')
    expect(notice.text()).toContain('FALLBACK')
  })

  it('只有助手轮次可选中，用户消息不承担选中交互', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')
    await wrapper.vm.$nextTick()

    // 两条消息，但只有助手那条渲染出可选中的按钮。之前 <article> 整卡可点，
    // 点用户消息会把 selectedRoundId 设成一个不存在的轮次，侧栏回落到最后一轮。
    expect(wrapper.findAll('[data-testid="chat-message"]')).toHaveLength(2)
    const selectors = wrapper.findAll('[data-testid="select-round"]')
    expect(selectors).toHaveLength(1)

    // 是真正的 button：可聚焦、可用键盘触发，不是挂了 click 的 article。
    expect(selectors[0].element.tagName).toBe('BUTTON')

    await selectors[0].trigger('click')
    expect(store.selectedRoundId).toBe(store.messages[1].localId)
  })

  it('上一轮在途时既拒绝新提交，也把输入区的发送按钮禁掉', async () => {
    setChatTransport(createMockTransport({ chunkSizes: [1], stepDelayMs: 5 }))
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    const pending = store.submitMessage('你好')
    await new Promise((resolve) => setTimeout(resolve, 10))
    await wrapper.vm.$nextTick()
    expect(store.isBusy).toBe(true)

    // Store 守卫：并发两轮会同时读到尚未回填的 sessionId，各自在服务端开一个
    // 新会话，前端却把两串回答混在同一条消息流里。
    const second = await store.submitMessage('昨天总 GMV 是多少？')
    expect(second).toBe(false)
    expect(store.messages).toHaveLength(2)

    // UI 守卫：用户根本敲不出第二轮，而不是敲了被静默丢弃。
    const send = wrapper.get('.chat-composer__send')
    expect(send.attributes('disabled')).toBeDefined()
    expect(send.attributes('aria-label')).toContain('仍在进行中')

    store.cancelMessage(store.messages[1].localId)
    await pending
    await wrapper.vm.$nextTick()
    expect(store.isBusy).toBe(false)
  })

  it('单轮时不显示轮次目录，两轮起才显示且点击能切回上一轮', async () => {
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    await store.submitMessage('昨天总 GMV 是多少？')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[data-testid="conversation-nav-item"]')).toHaveLength(0)

    const firstRound = store.messages[1].localId
    await store.submitMessage('我要货品上架，具体规则有吗？')
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('[data-testid="conversation-nav-item"]')
    expect(items).toHaveLength(2)
    // 目录条目显示的是本轮的提问，不是助手回答。
    expect(items[0].text()).toContain('昨天总 GMV 是多少？')
    expect(store.currentAnswer?.mode).toBe('RULE')

    await items[0].trigger('click')

    expect(store.selectedRoundId).toBe(firstRound)
    expect(store.currentAnswer?.mode).toBe('METRIC')
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

  it('流式阶段推进与完成后的最终答案都必须体现在渲染的 DOM 上，而不只是 Store 状态', async () => {
    // 回归用例：submitMessage 曾经把 push 之前的原始对象传给 runRound，
    // 而不是 push 之后从响应式数组里取出的代理对象。Store 层的断言（
    // store.messages[1].status === 'complete' 之类）读的是同一个代理，值本身
    // 是对的，所以纯 Store 测试完全测不出问题——必须挂载组件、断言真正渲染出
    // 来的 DOM 才能抓到「消息卡住不重渲染」这个 bug。
    //
    // chunkSizes 用比默认大很多的分片、stepDelayMs 保留一个很小的非零值：
    // 既保证整轮问答在两三百毫秒内跑完（测试够快），又保留至少一次真实的宏
    // 任务间隔，让「已经收到过 step、但流还没结束」的中间态真的可以被观察到，
    // 不会所有事件在同一个 microtask 里被一次性处理完。
    setChatTransport(createMockTransport({ chunkSizes: [40], stepDelayMs: 5 }))
    const wrapper = mount(ConversationColumn)
    const store = useChatStore()

    const pending = store.submitMessage('你好')
    const assistantLocalId = store.messages[1].localId
    const findAssistantMessage = () =>
      wrapper
        .findAllComponents(ChatMessage)
        .find((component) => component.props('message').localId === assistantLocalId)!

    // 中间态：阶段文案必须已经从占位符「正在准备」推进为具体的 step 标签。
    // 若 bug 还在，这里永远还是「正在准备」——组件从未因为 runRound 里的赋值
    // 而重新渲染过。
    await vi.waitFor(
      async () => {
        await wrapper.vm.$nextTick()
        expect(findAssistantMessage().get('[data-testid="stage-label"]').text()).not.toBe(
          '正在准备',
        )
      },
      { timeout: 1_000, interval: 10 },
    )
    expect(findAssistantMessage().find('[data-testid="cancel-button"]').exists()).toBe(true)

    await pending
    await wrapper.vm.$nextTick()

    // 完成态：阶段标签与停止按钮消失，真正的回答文本出现在 DOM 里。
    expect(findAssistantMessage().find('[data-testid="stage-label"]').exists()).toBe(false)
    expect(findAssistantMessage().text()).toContain('已完成结构化理解')
  })
})
