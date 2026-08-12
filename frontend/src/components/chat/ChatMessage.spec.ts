import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'
import { toChatAnswer } from '@/api/adapters/chat'
import detailOrder from '@fixtures/chat/detail-order.json'
import type { components } from '@/api/generated'
import type { ChatMessage as ChatMessageModel, QualityStatus } from '@/types/chat'

import ChatMessage from './ChatMessage.vue'

function makeMessage(overrides: Partial<ChatMessageModel> = {}): ChatMessageModel {
  return {
    localId: 'm1',
    clientRequestId: 'c1',
    role: 'assistant',
    text: '',
    createdAt: '2026-08-03T00:00:00Z',
    status: 'pending',
    steps: [],
    origin: 'live',
    ...overrides,
  }
}

describe('ChatMessage', () => {
  // DetailTable 在未收到 apiBaseUrl prop 时会读取 VITE_API_BASE_URL 拼下载链接
  // （ChatMessage.vue 不转发这个 prop，走的就是这条默认路径）。Vitest 以
  // mode=test 运行，不会加载 .env.development，这里必须显式提供，否则一挂载
  // 带明细数据的实时消息就会因 ApiConfigError 而渲染失败。
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('streaming 时展示最新阶段标签', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'streaming',
          steps: [
            { label: '识别商家与业务意图', node: 'classify' },
            { label: '读取业务口径并整理演示数据', node: 'compose' },
          ],
        }),
      },
    })

    expect(wrapper.get('[data-testid="stage-label"]').text()).toBe('读取业务口径并整理演示数据')
  })

  it('完成态实时消息按原顺序展示全部执行步骤', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'complete',
          text: '分析完成',
          steps: [
            { label: '识别商家与会话上下文', node: 'load_context' },
            { label: '查询经营数据', node: 'query_data' },
            { label: '保存回答', node: 'persist_answer' },
          ],
        }),
      },
    })

    expect(wrapper.findAll('[data-testid="thinking-step"]').map((item) => item.text())).toEqual([
      '识别商家与会话上下文',
      '查询经营数据',
      '保存回答',
    ])
  })

  it('完成态历史消息使用回答载荷中的完整执行步骤', () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    answer.thinkingSteps = [
      { label: '识别商家与会话上下文', node: 'load_context' },
      { label: '查询经营数据', node: 'query_data' },
      { label: '保存回答', node: 'persist_answer' },
    ]
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          origin: 'history',
          status: 'complete',
          text: '历史分析完成',
          steps: [],
          answer,
        }),
      },
    })

    expect(wrapper.findAll('[data-testid="thinking-step"]').map((item) => item.text())).toEqual([
      '识别商家与会话上下文',
      '查询经营数据',
      '保存回答',
    ])
  })

  it('error 时提供重试入口（retryable 错误）', async () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'error',
          error: new AppError('STREAM_INTERRUPTED', '回答流意外中断，请重试。', {
            retryable: true,
          }),
        }),
      },
    })

    await wrapper.get('[data-testid="retry-button"]').trigger('click')

    expect(wrapper.emitted('retry')).toEqual([['m1']])
    expect(wrapper.text()).toContain('回答流意外中断')
  })

  it('不可重试的错误（如 REQUEST_IN_PROGRESS）不展示重试按钮', () => {
    // 后端说这条请求正在处理，再点重试会打成循环——UI 只展示提示文案，
    // 等待而非重发。
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'error',
          error: new AppError('REQUEST_IN_PROGRESS', '上一条请求仍在处理', { retryable: false }),
        }),
      },
    })

    expect(wrapper.find('[data-testid="retry-button"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('仍在处理')
  })

  it('cancelled 的文案与 error 不同，且不说「出错」', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'cancelled',
          error: new AppError('CANCELLED', '请求已取消', { retryable: true }),
        }),
      },
    })

    expect(wrapper.text()).toContain('已取消')
    expect(wrapper.text()).not.toContain('出错')
  })

  it('cancelled 消息始终提供重试入口，不受 error.retryable 影响', async () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'cancelled',
          error: new AppError('CANCELLED', '请求已取消', { retryable: false }),
        }),
      },
    })

    expect(wrapper.find('[data-testid="retry-button"]').exists()).toBe(true)
    await wrapper.get('[data-testid="retry-button"]').trigger('click')
    expect(wrapper.emitted('retry')).toEqual([['m1']])
  })

  it('streaming 时提供取消入口', async () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ status: 'streaming', steps: [{ label: '识别', node: 'c' }] }),
      },
    })

    await wrapper.get('[data-testid="cancel-button"]').trigger('click')

    expect(wrapper.emitted('cancel')).toEqual([['m1']])
  })

  it('实时明细回答在消息内渲染表格，而不是挤进侧栏', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'complete',
          text: '订单明细已查询完成',
          answer: toChatAnswer(detailOrder as components['schemas']['ChatResponse']),
        }),
      },
    })

    expect(wrapper.find('[data-testid="detail-table"]').exists()).toBe(true)
  })

  it('历史明细回答不重新渲染表格，改为提示重新提问', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          origin: 'history',
          status: 'complete',
          text: '订单明细已查询完成',
          answer: toChatAnswer(detailOrder as components['schemas']['ChatResponse']),
        }),
      },
    })

    expect(wrapper.find('[data-testid="detail-table"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="history-detail-notice"]').text()).toContain('重新提问')
  })

  it.each([
    ['PASSED', '前后比对通过'],
    ['DEGRADED', '校验未通过，已使用稳定兜底'],
    ['FAILED', '前后比对未通过'],
    ['NOT_RUN', '未执行校验'],
  ] as const)('%s 质量状态如实显示为中文', (status, label) => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    answer.quality = { ...answer.quality, status }
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage({ status: 'complete', text: '回答', answer }) },
    })

    const trace = wrapper.get('[aria-label="质量校验轨迹"]')
    expect(trace.text()).toContain(label)
  })

  it.each([
    [0, false, ''],
    [1, true, '经过 1 次校验'],
    [2, true, '经过 2 次校验'],
  ] as const)('校验次数为 %i 时按约定显示', (attempts, visible, label) => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    answer.quality = { ...answer.quality, status: 'PASSED', attempts }
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage({ status: 'complete', text: '回答', answer }) },
    })

    expect(wrapper.find('[data-testid="quality-attempts"]').exists()).toBe(visible)
    if (visible) expect(wrapper.get('[data-testid="quality-attempts"]').text()).toBe(label)
    expect(wrapper.text()).not.toContain('RETRIED')
  })

  it('来源按数组顺序全部显示为中文，降级提示也不泄露枚举字面量', () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    answer.quality = {
      status: 'DEGRADED',
      attempts: 1,
      notes: [],
      sources: ['DATABASE', 'KNOWLEDGE', 'FALLBACK'],
      degraded: true,
      degradedReason: '部分分析能力暂不可用。',
    }
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage({ status: 'complete', text: '回答', answer }) },
    })

    const sources = wrapper.findAll('[data-testid="quality-source"]').map((item) => item.text())
    expect(sources).toEqual(['经营数据', '知识库', '兜底回答'])
    expect(wrapper.text()).not.toMatch(/DATABASE|KNOWLEDGE|FALLBACK/)
  })

  it('有校验记录时可展开查看，没有记录时不渲染折叠块', () => {
    const withNotes = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    withNotes.quality = {
      ...withNotes.quality,
      status: 'FAILED' as QualityStatus,
      notes: ['金额字段与查询结果不一致', '已停止生成经营建议'],
    }
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage({ status: 'complete', text: '回答', answer: withNotes }) },
    })

    const details = wrapper.get('[data-testid="quality-notes"]')
    expect(details.element.tagName).toBe('DETAILS')
    expect(details.text()).toContain('查看校验记录')
    expect(details.text()).toContain('金额字段与查询结果不一致')

    const withoutNotes = { ...withNotes, quality: { ...withNotes.quality, notes: [] } }
    expect(
      mount(ChatMessage, {
        props: { message: makeMessage({ status: 'complete', text: '回答', answer: withoutNotes }) },
      })
        .find('[data-testid="quality-notes"]')
        .exists(),
    ).toBe(false)
  })

  it('没有 answer.id 的历史消息不渲染反馈按钮组', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ origin: 'history', status: 'complete', text: '历史回答' }),
      },
    })

    expect(wrapper.find('[aria-label="回答反馈"]').exists()).toBe(false)
  })

  it('历史回答缺少服务端反馈状态时不开放反馈操作', () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ origin: 'history', status: 'complete', text: '历史回答', answer }),
      },
    })

    expect(wrapper.find('[aria-label="回答反馈"]').exists()).toBe(false)
  })

  it('三个反馈按钮发出明确意图并暴露可访问名称', async () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage({ status: 'complete', text: '回答', answer }) },
    })

    await wrapper.get('[aria-label="采纳本轮回答"]').trigger('click')
    await wrapper.get('[aria-label="给本轮回答点赞"]').trigger('click')
    await wrapper.get('[aria-label="给本轮回答点踩"]').trigger('click')

    expect(wrapper.emitted('feedback')).toEqual([
      ['m1', { type: 'ADOPT' }],
      ['m1', { type: 'REACT', reaction: 'LIKE' }],
      ['m1', { type: 'REACT', reaction: 'DISLIKE' }],
    ])
  })

  it('选中状态用 aria-pressed 表达', () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'complete',
          text: '回答',
          answer,
          feedback: { isAdopted: true, reaction: 'LIKE' },
        }),
      },
    })

    expect(wrapper.get('[aria-label="采纳本轮回答"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[aria-label="给本轮回答点赞"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[aria-label="给本轮回答点踩"]').attributes('aria-pressed')).toBe('false')
  })

  it('保存中禁用全部按钮并显示保存中，不提前声称已记录', () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'complete',
          text: '回答',
          answer,
          feedback: { isAdopted: true, reaction: null },
          feedbackPending: true,
        }),
      },
    })

    expect(wrapper.get('[data-testid="feedback-status"]').text()).toBe('保存中')
    expect(wrapper.text()).not.toContain('已记录')
    for (const button of wrapper.findAll('[aria-label^="采纳本轮"], [aria-label^="给本轮"]')) {
      expect(button.attributes('disabled')).toBeDefined()
    }
  })

  it('本地反馈未确认时不显示已记录，服务端确认后才显示', async () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    const message = makeMessage({
      status: 'complete',
      text: '回答',
      answer,
      feedback: { isAdopted: true, reaction: null },
    })
    const wrapper = mount(ChatMessage, { props: { message } })

    expect(wrapper.find('[data-testid="feedback-status"]').exists()).toBe(false)

    await wrapper.setProps({ message: { ...message, feedbackPersisted: true } })
    expect(wrapper.get('[data-testid="feedback-status"]').text()).toBe('已记录')
  })

  it('反馈失败提示可感知，且保留按钮选中态供重试', () => {
    const answer = toChatAnswer(detailOrder as components['schemas']['ChatResponse'])
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          status: 'complete',
          text: '回答',
          answer,
          feedback: { isAdopted: true, reaction: null },
          feedbackError: new AppError('NETWORK', '网络不可用', { retryable: true }),
        }),
      },
    })

    expect(wrapper.get('[data-testid="feedback-error"]').attributes('aria-live')).toBe('polite')
    expect(wrapper.get('[data-testid="feedback-error"]').text()).toContain('网络')
    expect(wrapper.get('[aria-label="采纳本轮回答"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[aria-label="采纳本轮回答"]').attributes('disabled')).toBeUndefined()
  })
})
