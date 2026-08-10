import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'
import { toChatAnswer } from '@/api/adapters/chat'
import detailOrder from '@fixtures/chat/detail-order.json'
import type { components } from '@/api/generated'
import type { ChatMessage as ChatMessageModel } from '@/types/chat'

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
})
