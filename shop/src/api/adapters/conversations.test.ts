import { describe, expect, it } from 'vitest'
import type { components } from '../generated'
import { toConversationMessage, toConversationSummary } from './conversations'

type S = components['schemas']

describe('会话目录 wire → 领域模型', () => {
  it('摘要只取契约字段', () => {
    const raw: S['ShopConversationSummary'] = {
      id: 'c1', title: '围巾怎么选', created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-02T00:00:00Z',
    }
    expect(toConversationSummary(raw)).toEqual({
      id: 'c1', title: '围巾怎么选', createdAt: '2026-09-01T00:00:00Z', updatedAt: '2026-09-02T00:00:00Z',
    })
  })

  it('助手消息的完整回答复用 Chat 的同一个 Adapter；提问消息没有回答', () => {
    const user: S['ShopConversationMessage'] = {
      id: 'm1', role: 'user', content: '围巾怎么选', created_at: '2026-09-01T00:00:00Z', answer: null,
    }
    const assistant: S['ShopConversationMessage'] = {
      id: 'm2', role: 'assistant', content: '羊绒更暖', created_at: '2026-09-01T00:00:01Z',
      answer: {
        id: 'a1', conversation_id: 'c1', answer: '羊绒更暖', created_at: '2026-09-01T00:00:01Z',
        tool_calls: [{ tool_name: 'search_products', call_id: 't1', status: 'SUCCEEDED', summary: '处理完成' }],
        analysis_sources: [], quality_status: 'PASSED', quality_attempts: 1,
        degraded: true, degraded_reason: '知识库暂不可用', answer_mode: 'SHOP_GUIDE',
      } as S['ShopChatResponse'],
    }
    expect(toConversationMessage(user)).toEqual({
      id: 'm1', role: 'user', content: '围巾怎么选', createdAt: '2026-09-01T00:00:00Z', turn: null,
    })
    const mapped = toConversationMessage(assistant)
    expect(mapped.turn).toMatchObject({
      conversationId: 'c1', degraded: true, degradedReason: '知识库暂不可用', suggestions: [],
      toolCalls: [{ toolName: 'search_products', callId: 't1', status: 'SUCCEEDED', summary: '处理完成' }],
    })
  })
})
