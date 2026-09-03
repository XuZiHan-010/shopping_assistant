import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { AppError } from '@/api/errors'
import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport, type TransportRequest } from '@/api/transport'
import ConversationColumn from '@/components/chat/ConversationColumn.vue'
import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import { useAppError } from '@/composables/useAppError'
import { i18n, type SupportedLocale } from '@/i18n'
import router from '@/router'
import { MERCHANT_STORAGE_KEY, useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useLocaleStore } from '@/stores/locale'
import type { ChatMessage } from '@/types/chat'
import AssistantView from './AssistantView.vue'

describe('AssistantView', () => {
  /**
   * 每个用例都 attachTo document.body，不卸载就不会触发 onBeforeUnmount。
   * AssistantView 的图表挂载兜底定时器（jsdom 没有 requestIdleCallback，走 setTimeout 分支）
   * 会一直挂着，等环境拆除之后才 fire，进而发起 MetricChartPanel 的动态 import，
   * 报出 "caught after test environment was torn down"。
   */
  const mountedWrappers: VueWrapper[] = []

  beforeEach(() => {
    setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
    sessionStorage.clear()
    // useAppError 是模块级单例，不清会把上一条断言的提示带进下一个用例。
    useAppError().clearError()
  })

  afterEach(() => {
    while (mountedWrappers.length > 0) mountedWrappers.pop()?.unmount()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  /**
   * 商家名不再是硬编码常量，而是挂载后由 Auth Store 异步取回的（F2 Task 9）。
   * 断言商家菜单之前必须把这次加载 flush 掉，否则菜单里一个选项都还没有。
   *
   * `locale` 默认 zh-CN，保持既有中文断言不受影响；`i18n.global.locale` 是
   * 跨用例共享的模块级单例（LanguageSwitcher 等组件同一套用法），每次挂载显式
   * 通过 `useLocaleStore().setLocale()` 校准，不依赖上一个用例残留的语言状态。
   */
  async function mountView(locale: SupportedLocale = 'zh-CN') {
    const pinia = createPinia()
    setActivePinia(pinia)
    useLocaleStore().setLocale(locale)
    const wrapper = mount(AssistantView, {
      // 焦点断言只有在真的挂进文档里才成立——游离节点上 focus() 是空操作。
      attachTo: document.body,
      global: {
        plugins: [pinia, i18n],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    mountedWrappers.push(wrapper)
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

  it('顶栏知识库入口带文字标签，不是纯图标（新用户可发现性）', async () => {
    const wrapper = await mountView()
    const link = wrapper.get('.knowledge-link')

    expect(link.text()).toContain('知识库')
  })

  it('顶栏提供可发现的 Chat BI 运营看板入口', async () => {
    const wrapper = await mountView()
    const link = wrapper.get('.ops-link')

    expect(link.text()).toContain('看板')
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
    // listConversations 现在带 ?limit= 查询串，用 startsWith 匹配路径前缀。
    expect(order.findIndex((path) => path.startsWith('/api/demo/merchants'))).toBeLessThan(
      order.findIndex((path) => path.startsWith('/api/conversations')),
    )
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
      origin: 'live',
    }
    chatStore.messages.push(seedMessage)

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家100"]').trigger('click')
    expect(chatStore.isEmptyConversation).toBe(false)

    await wrapper.get('button[aria-label="切换当前演示商家"]').trigger('click')
    await wrapper.get('[data-merchant="Borough商家101"]').trigger('click')
    expect(chatStore.isEmptyConversation).toBe(true)
  })

  /**
   * MVP 没有登录页——`/login` 会落到 `not-found` 兜底，跳过去就是一个 404。
   * Token 失效必须原地恢复：清掉作废的身份、把选择权交还给切换器，同时不能
   * 把用户刚写完还没发出去的问题一起清掉，否则一次身份失效就变成一次数据丢失。
   */
  it('401 清凭证、开切换器、保留未发送输入，且不跳路由', async () => {
    const healthy = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    setChatTransport(async (request: TransportRequest, signal: AbortSignal) => {
      if (request.path === '/api/chat' && request.method === 'POST') {
        throw new AppError('AUTH_REQUIRED', '演示身份已失效', { status: 401 })
      }
      return healthy(request, signal)
    })

    const wrapper = await mountView()

    await wrapper.get('textarea').setValue('昨天的 GMV 是多少')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(useAuthStore().selected?.token).toBeUndefined()
    expect(sessionStorage.getItem(MERCHANT_STORAGE_KEY)).toBeNull()
    expect(wrapper.get('[data-testid="merchant-switcher"]').attributes('aria-expanded')).toBe(
      'true',
    )
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('昨天的 GMV 是多少')
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('首屏只渲染图表占位，不挂载图表面板', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useLocaleStore().setLocale('zh-CN')
    const wrapper = mount(AssistantView, {
      global: { plugins: [pinia, i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    mountedWrappers.push(wrapper)

    const placeholder = wrapper.find('[data-testid="chart-placeholder"]')
    expect(placeholder.exists()).toBe(true)
    expect(placeholder.attributes('aria-busy')).toBe('false')
    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(false)
  })

  it('空闲回调触发后挂载图表面板', async () => {
    let idleCallback: (() => void) | undefined
    vi.stubGlobal('requestIdleCallback', (callback: () => void) => {
      idleCallback = callback
      return 1
    })

    const pinia = createPinia()
    setActivePinia(pinia)
    useLocaleStore().setLocale('zh-CN')
    const wrapper = mount(AssistantView, {
      global: {
        plugins: [pinia, i18n],
        stubs: {
          MetricChartPanel: { template: '<section data-testid="chart-mounted" />' },
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })

    expect(idleCallback).toBeTypeOf('function')
    idleCallback!()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="chart-mounted"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('不支持 requestIdleCallback 时回退到定时器，并在卸载时取消', () => {
    vi.stubGlobal('requestIdleCallback', undefined)
    const setTimeoutSpy = vi.fn(() => 42)
    const clearTimeoutSpy = vi.fn()
    vi.stubGlobal('setTimeout', setTimeoutSpy)
    vi.stubGlobal('clearTimeout', clearTimeoutSpy)

    const pinia = createPinia()
    setActivePinia(pinia)
    useLocaleStore().setLocale('zh-CN')
    const wrapper = mount(AssistantView, {
      global: { plugins: [pinia, i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })

    expect(setTimeoutSpy).toHaveBeenCalled()
    wrapper.unmount()
    expect(clearTimeoutSpy).toHaveBeenCalledWith(42)
  })

  /**
   * Q8 裁定「本轮按整份日报采纳」——卡片只有一个按钮，点击必须只提交
   * answer-level 的 {is_adopted, reaction}，不能编造建议级 id。
   */
  it('采纳日报只提交整份日报级别的反馈，不带建议级 id', async () => {
    const healthy = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    const feedbackRequests: unknown[] = []
    setChatTransport(async (request: TransportRequest, signal: AbortSignal) => {
      if (request.path.startsWith('/api/answers/') && request.method === 'POST') {
        feedbackRequests.push(request.body)
        return new Response(JSON.stringify({ is_adopted: true, reaction: null }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return healthy(request, signal)
    })

    const wrapper = await mountView()
    await flushPromises()

    const adoptButton = wrapper.get('.daily-report__adopt')
    await adoptButton.trigger('click')
    await flushPromises()

    expect(feedbackRequests).toEqual([{ is_adopted: true, reaction: null }])
    expect(adoptButton.text()).toContain('已采纳本期建议')
  })

  it('日报降级时展示降级原因，不展示指标网格（不得用假数据顶替）', async () => {
    const healthy = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })
    setChatTransport(async (request: TransportRequest, signal: AbortSignal) => {
      if (request.path === '/api/reports/daily' && request.method === 'GET') {
        return new Response(
          JSON.stringify({
            answer_id: '00000000-0000-0000-0000-0000000000f1',
            report_date: '2026-08-20',
            metrics: [],
            suggestions: ['建议一', '建议二'],
            degraded: true,
            degraded_reason: '查询失败，暂无法生成经营数据摘要',
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        )
      }
      return healthy(request, signal)
    })

    const wrapper = await mountView()
    await flushPromises()

    expect(wrapper.find('.daily-report__degraded').text()).toContain(
      '查询失败，暂无法生成经营数据摘要',
    )
    expect(wrapper.find('.daily-report__metrics').exists()).toBe(false)
  })

  it('日报加载失败时提示错误，且不阻塞主界面其余功能', async () => {
    setChatTransport(transportFailingOn('/api/reports/daily'))

    const wrapper = await mountView()
    await flushPromises()

    expect(useAppError().message.value).toContain('每日经营日报加载失败')
    expect(wrapper.find('.daily-report').exists()).toBe(false)
    expect(wrapper.find('textarea[aria-label="输入问题"]').exists()).toBe(true)
  })

  /**
   * Task 10B Step 1/5：英语失败测试→迁移确定性文案→回归通过。断言范围覆盖
   * 标题、推荐问题、输入提示、发送/停止按钮、历史空态、每日经营报告、质量
   * 轨迹、反馈、明细表、建议；技术字段（SQL 口径、URL、ID、数值、
   * `metric_code`）保持原值，不被翻译。
   *
   * 提交给 Mock 后端的问题原文仍用中文关键词（`api/mock/scenarios.ts` 目前
   * 只认中文关键词，双语 Mock 匹配是 Task 11 的职责范围），这里验证的是
   * UI chrome 本身在英语模式下的渲染，不依赖 Mock 层已完成双语改造。
   */
  it('en-US 下助手页确定性文案全部为英文，技术字段和后端已本地化内容保持原值', async () => {
    const wrapper = await mountView('en-US')

    // 页头：标题、Tagline、知识库/看板入口、新会话按钮、语言切换器。
    expect(wrapper.text()).toContain('Borough Merchant AI Assistant')
    expect(wrapper.text()).toContain('Business data, analysis, and action recommendations')
    expect(wrapper.get('.knowledge-link').text()).toContain('Knowledge base')
    expect(wrapper.get('.ops-link').text()).toContain('Dashboard')
    expect(wrapper.get('.new-chat-button').text()).toContain('New chat')
    expect(wrapper.find('[data-testid="language-switcher"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="language-switcher"]').attributes('aria-label')).toBe(
      'Switch to Chinese',
    )

    // 输入区：placeholder、aria-label、发送按钮、脚注提示。
    expect(wrapper.get('textarea').attributes('aria-label')).toBe('Ask a question')
    expect(wrapper.get('textarea').attributes('placeholder')).toBe('Ask a business question…')
    expect(wrapper.text()).toContain('Enter to send')

    // 推荐问题（欢迎卡片的快速体验区）。
    expect(wrapper.text()).toContain("Hi, I'm your business assistant")
    expect(wrapper.text()).toContain('Quick start')
    const quickQuestionButtons = wrapper.findAll('[data-testid="quick-question"]')
    expect(quickQuestionButtons.length).toBeGreaterThan(0)
    expect(quickQuestionButtons[0].text()).not.toMatch(/[一-龥]/)

    // 图表占位（首屏，图表面板尚未挂载）。
    expect(wrapper.get('[data-testid="chart-placeholder"]').text()).toContain(
      'Ask a visualization-friendly question',
    )

    // 每日经营报告卡片：标题、日期、采纳按钮。
    expect(wrapper.text()).toContain('Daily business report')
    expect(wrapper.get('.daily-report__adopt').text()).toContain('Adopt this report')

    // 历史空态：打开对话目录，断言英文空态文案（复用 Task 10A 已完成的
    // ConversationDrawer 本地化成果）。
    await wrapper.get('button[aria-label="Open conversation history"]').trigger('click')
    expect(wrapper.text()).toContain('No conversation history yet')
    await wrapper.get('button[aria-label="Close conversation history"]').trigger('click')

    // 发起一轮真实问答（提交文本本身仍是中文关键词，命中 Mock 的
    // metricGmv fixture；这里只验证 UI chrome，不依赖 Mock 双语匹配）。
    const chatStore = useChatStore()
    await chatStore.submitMessage('昨天总 GMV 是多少？')
    await flushPromises()

    // 质量轨迹、反馈按钮、建议面板、指标口径面板均为英文 chrome。
    expect(wrapper.get('[aria-label="Quality review trace"]').text()).toMatch(
      /Reviewed|passed|fallback/i,
    )
    expect(wrapper.get('[aria-label="Adopt this answer"]').text()).toContain('Adopt')
    expect(wrapper.get('[aria-label="Like this answer"]').text()).toContain('Like')
    expect(wrapper.get('[aria-label="Dislike this answer"]').text()).toContain('Dislike')
    expect(wrapper.text()).toContain('Metric definition')
    expect(wrapper.text()).toContain('Action recommendations')
    expect(wrapper.text()).toContain('You might also ask')

    // 技术字段原样保留：metric_code、SQL 口径关键字、数值本身不被翻译。
    const answer = chatStore.currentAnswer
    expect(answer?.metric?.code).toBe('gmv')
    expect(wrapper.text()).toMatch(/SELECT|FROM|SUM/i)
  })
})
