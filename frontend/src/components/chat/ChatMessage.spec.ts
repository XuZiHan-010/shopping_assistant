import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

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
    ...overrides,
  }
}

describe('ChatMessage', () => {
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

  it('error 时提供重试入口', async () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ status: 'error', errorMessage: '回答流意外中断，请重试。' }),
      },
    })

    await wrapper.get('[data-testid="retry-button"]').trigger('click')

    expect(wrapper.emitted('retry')).toEqual([['m1']])
    expect(wrapper.text()).toContain('回答流意外中断')
  })

  it('cancelled 的文案与 error 不同，且不说「出错」', () => {
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage({ status: 'cancelled', errorMessage: '已取消本次回答。' }) },
    })

    expect(wrapper.text()).toContain('已取消')
    expect(wrapper.text()).not.toContain('出错')
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
})
