import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'

import {
  deleteMerchantConversation,
  fetchMerchantConversationHistory,
  fetchMerchantConversations,
  streamMerchantChat,
  submitMerchantFeedback,
  toMerchantTurn,
} from './merchantConversations'

const BASE_URL = 'http://127.0.0.1:8000'
const SESSION = 's'.repeat(43)

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function rawAnswer(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a-1',
    conversation_id: 'c-1',
    answer: '有 1 个商品低库存。',
    tool_calls: [
      {
        tool_name: 'get_inventory_alerts',
        call_id: 't-1',
        status: 'SUCCEEDED',
        summary: '处理完成',
      },
    ],
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    quality_status: 'PASSED',
    quality_attempts: 1,
    degraded: false,
    degraded_reason: null,
    created_at: '2026-09-24T00:00:01Z',
    answer_mode: 'MERCHANT_OPS',
    ...overrides,
  }
}

function summary(id: string, title: string) {
  return { id, title, created_at: '2026-09-24T00:00:00Z', updated_at: '2026-09-24T00:00:00Z' }
}

function calls(): { url: string; init: RequestInit }[] {
  return vi.mocked(fetch).mock.calls.map(([url, init]) => ({ url: String(url), init: init ?? {} }))
}

beforeEach(() => vi.stubEnv('VITE_API_BASE_URL', BASE_URL))
afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('merchantConversations Adapter', () => {
  it('反馈：采纳与赞踩发送互斥字段，并转换完整响应', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          answer_id: 'a-1',
          adopted: true,
          reaction: 'LIKE',
          reason: '有帮助',
          updated_at: '2026-09-24T00:00:02Z',
        }),
      ),
    )
    const result = await submitMerchantFeedback(SESSION, 'a-1', {
      clientRequestId: 'req-1',
      kind: 'REACTION',
      reaction: 'LIKE',
      reason: '有帮助',
    })
    expect(result).toEqual({ adopted: true, reaction: 'LIKE', reason: '有帮助' })
    const [{ url, init }] = calls()
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/answers/a-1/feedback`)
    expect(JSON.parse(init.body as string)).toEqual({
      client_request_id: 'req-1',
      kind: 'REACTION',
      reaction: 'LIKE',
      reason: '有帮助',
    })
    expect((init.headers as Record<string, string>)['X-Session-Id']).toBe(SESSION)
  })
  it('toMerchantTurn：最终响应经 parseFinalResponse，工具行只取展示字段，猜你想问缺省为空', () => {
    const turn = toMerchantTurn(
      rawAnswer({
        degraded: true,
        degraded_reason: '库存数据暂不可用',
        tool_calls: [
          {
            tool_name: 'draft_restock',
            call_id: 't-2',
            status: 'SUCCEEDED',
            summary: '处理完成',
            arguments: { product_id: 'SECRET' },
          },
        ],
      }) as never,
    )
    expect(turn).toMatchObject({ id: 'a-1', conversationId: 'c-1', suggestions: [] })
    expect(turn.chart).toEqual({ enabled: false, allowedTypes: [], data: [] })
    expect(turn.envelope).toMatchObject({
      answer: '有 1 个商品低库存。',
      degraded: true,
      degradedReason: '库存数据暂不可用',
    })
    expect(turn.toolCalls).toEqual([
      { toolName: 'draft_restock', callId: 't-2', status: 'SUCCEEDED', summary: '处理完成' },
    ])
  })

  it('toMerchantTurn：图表可视化字段原样映射为驼峰键（供 MetricChartPanel 直接消费）', () => {
    const turn = toMerchantTurn(
      rawAnswer({
        visualization: {
          enabled: true,
          type: 'LINE',
          allowed_types: ['LINE'],
          title: '成交总额趋势',
          dimension_key: 'date',
          metric_key: 'gross_gmv',
          unit: '元',
          data: [{ date: '2026-09-20', gross_gmv: '100' }],
        },
      }) as never,
    )

    expect(turn.chart).toEqual({
      enabled: true,
      type: 'LINE',
      allowedTypes: ['LINE'],
      title: '成交总额趋势',
      dimensionKey: 'date',
      metricKey: 'gross_gmv',
      unit: '元',
      data: [{ date: '2026-09-20', gross_gmv: '100' }],
    })
  })

  it('列表：会话 ID 只进请求头，带显示语言，按 cursor 翻页', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ items: [summary('c-1', '库存怎么样')], next_cursor: 'N', has_more: true }),
        ),
    )
    const page = await fetchMerchantConversations(SESSION, 'CUR')
    expect(page).toEqual({
      items: [
        {
          id: 'c-1',
          title: '库存怎么样',
          createdAt: '2026-09-24T00:00:00Z',
          updatedAt: '2026-09-24T00:00:00Z',
        },
      ],
      nextCursor: 'N',
      hasMore: true,
    })
    const [{ url, init }] = calls()
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/conversations?cursor=CUR&limit=20`)
    expect(url).not.toContain(SESSION)
    const headers = init.headers as Record<string, string>
    expect(headers['X-Session-Id']).toBe(SESSION)
    expect(headers['Accept-Language']).toMatch(/zh-CN|en-US/)
  })

  it('历史：沿 next_cursor 逐页取完，助手消息带完整回答', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({
            conversation: summary('c-1', 't'),
            messages: {
              items: [
                {
                  id: 'm-1',
                  role: 'user',
                  content: '库存怎么样',
                  created_at: '2026-09-24T00:00:00Z',
                  answer: null,
                  feedback: null,
                },
              ],
              next_cursor: 'M2',
              has_more: true,
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            conversation: summary('c-1', 't'),
            messages: {
              items: [
                {
                  id: 'm-2',
                  role: 'assistant',
                  content: '有 1 个商品低库存。',
                  created_at: '2026-09-24T00:00:01Z',
                  answer: rawAnswer(),
                  feedback: { adopted: true, reaction: 'DISLIKE', reason: '不准确' },
                },
              ],
              next_cursor: null,
              has_more: false,
            },
          }),
        ),
    )
    const history = await fetchMerchantConversationHistory(SESSION, 'c-1')
    expect(history.truncated).toBe(false)
    expect(history.messages.map((m) => [m.role, m.content])).toEqual([
      ['user', '库存怎么样'],
      ['assistant', '有 1 个商品低库存。'],
    ])
    expect(history.messages[0]!.turn).toBeNull()
    expect(history.messages[1]!.turn?.toolCalls[0]?.toolName).toBe('get_inventory_alerts')
    expect(history.messages[1]!.feedback).toEqual({
      adopted: true,
      reaction: 'DISLIKE',
      reason: '不准确',
    })
    expect(calls()[1]!.url).toBe(
      `${BASE_URL}/api/v2/merchant/conversations/c-1?cursor=M2&limit=100`,
    )
  })

  it('删除：DELETE 204；越权或已删除按 AppError 抛出', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(jsonResponse(null, 204)))
    await deleteMerchantConversation(SESSION, 'c-1')
    expect(calls()[0]!.init.method).toBe('DELETE')

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        jsonResponse(
          {
            code: 'RESOURCE_FORBIDDEN',
            message: 'x',
            request_id: 'r',
            details: [],
            retryable: false,
          },
          403,
        ),
      ),
    )
    await expect(deleteMerchantConversation(SESSION, 'c-9')).rejects.toBeInstanceOf(AppError)
  })

  it('Chat 流：只发契约字段，SSE 请求头齐全，解析到 turn_complete', async () => {
    const body = `event: tool_call\ndata: ${JSON.stringify({ tool_name: 'get_inventory_alerts', call_id: 't-1', status: 'STARTED', summary: '正在处理' })}\n\nevent: turn_complete\ndata: ${JSON.stringify(rawAnswer())}\n\n`
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
        ),
    )
    const events = []
    for await (const event of streamMerchantChat(SESSION, {
      clientRequestId: 'r-1',
      message: '库存',
      conversationId: 'c-1',
    })) {
      events.push(event.type)
    }
    expect(events).toEqual(['tool_call', 'turn_complete'])
    const [{ url, init }] = calls()
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/chat`)
    expect(JSON.parse(init.body as string)).toEqual({
      client_request_id: 'r-1',
      message: '库存',
      conversation_id: 'c-1',
    })
    const headers = init.headers as Record<string, string>
    expect(headers.Accept).toBe('text/event-stream')
    expect(headers['Content-Type']).toBe('application/json')
    expect(headers['X-Session-Id']).toBe(SESSION)
  })
})
