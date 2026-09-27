import { describe, expect, it } from 'vitest'

import { ChatStreamInterruptedError } from '@/api/sse'

import { readMerchantChatStream } from './chatV2'

/**
 * 载荷形状逐字按契约 §8.7.5 写，不按实现猜：
 * - `tool_call`：`{ tool_name, call_id, status, summary }`
 * - `tool_result`：`{ call_id, status, duration_ms, row_count, summary }`——**没有 tool_name**
 * - `status` 取 `ToolDisplayStatus` 闭集（STARTED / RUNNING / SUCCEEDED / DEGRADED / FAILED / UNAVAILABLE）
 * 与后端 `tests/integration/v2/test_merchant_chat.py::test_sse_stream_ends_with_turn_complete`
 * 断言的键集合一致。
 */
const TOOL_CALL = {
  tool_name: 'get_inventory_alerts',
  call_id: 'c1',
  status: 'STARTED',
  summary: '正在处理',
}
const TOOL_RESULT = {
  call_id: 'c1',
  status: 'SUCCEEDED',
  duration_ms: 12,
  row_count: 3,
  summary: '处理完成',
}

function streamOf(bytes: Uint8Array, sizes: number[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      let offset = 0
      let index = 0
      while (offset < bytes.length) {
        const size = sizes[index % sizes.length]!
        controller.enqueue(bytes.slice(offset, offset + size))
        offset += size
        index += 1
      }
      controller.close()
    },
  })
}

function turnCompletePayload(overrides: Record<string, unknown> = {}) {
  return {
    id: 'msg-1',
    conversation_id: 'conv-1',
    answer: '已为你查询库存告警',
    answer_mode: 'CHAT',
    tool_calls: [{ ...TOOL_CALL, status: 'SUCCEEDED', summary: '处理完成' }],
    created_at: '2026-09-23T00:00:00Z',
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [],
    quality_status: 'NOT_RUN',
    quality_attempts: 0,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
    ...overrides,
  }
}

function encodeStream(events: { event: string; data: unknown }[]): Uint8Array {
  let text = ''
  for (const { event, data } of events) {
    text += `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
  }
  return new TextEncoder().encode(text)
}

async function collect(bytes: Uint8Array, size = 32) {
  const events = []
  for await (const event of readMerchantChatStream(streamOf(bytes, [size]))) {
    events.push(event)
  }
  return events
}

describe('readMerchantChatStream', () => {
  it.each([[1], [3], [7], [64]])(
    '按 %i 字节切块仍能还原 step/tool_call/tool_result/turn_complete',
    async (size) => {
      const events = await collect(
        encodeStream([
          { event: 'step', data: { label: '查询库存', node: 'query' } },
          { event: 'tool_call', data: TOOL_CALL },
          { event: 'tool_result', data: TOOL_RESULT },
          { event: 'turn_complete', data: turnCompletePayload() },
        ]),
        size,
      )

      expect(events.map((event) => event.type)).toEqual([
        'step',
        'tool_call',
        'tool_result',
        'turn_complete',
      ])
      const last = events.at(-1)
      expect(last?.type === 'turn_complete' && last.raw.answer).toBe('已为你查询库存告警')
    },
  )

  it('step 事件与 v1 同名同构，直通领域 ThinkingStep', async () => {
    const [event] = await collect(
      encodeStream([
        { event: 'step', data: { label: '查询库存', node: 'query' } },
        { event: 'turn_complete', data: turnCompletePayload() },
      ]),
    )

    expect(event).toEqual({ type: 'step', step: { label: '查询库存', node: 'query' } })
  })

  it('tool_call 转成领域形状：工具名、状态、固定短句', async () => {
    const [event] = await collect(
      encodeStream([
        { event: 'tool_call', data: TOOL_CALL },
        { event: 'turn_complete', data: turnCompletePayload() },
      ]),
    )

    expect(event).toEqual({
      type: 'tool_call',
      call: {
        toolName: 'get_inventory_alerts',
        callId: 'c1',
        status: 'STARTED',
        summary: '正在处理',
      },
    })
  })

  it('tool_result 转成领域形状：耗时、行数，不含工具名也不含任何结果正文', async () => {
    const [event] = await collect(
      encodeStream([
        { event: 'tool_result', data: TOOL_RESULT },
        { event: 'turn_complete', data: turnCompletePayload() },
      ]),
    )

    expect(event).toEqual({
      type: 'tool_result',
      result: {
        callId: 'c1',
        status: 'SUCCEEDED',
        durationMs: 12,
        rowCount: 3,
        summary: '处理完成',
      },
    })
  })

  it('tool_result 的 row_count 不适用时为 null，原样保留不折成 0', async () => {
    const [event] = await collect(
      encodeStream([
        { event: 'tool_result', data: { ...TOOL_RESULT, row_count: null } },
        { event: 'turn_complete', data: turnCompletePayload() },
      ]),
    )

    expect(event?.type === 'tool_result' && event.result.rowCount).toBeNull()
  })

  it('turn_complete 事件带上与 v1 done 共用的最终响应 envelope', async () => {
    const events = await collect(
      encodeStream([{ event: 'turn_complete', data: turnCompletePayload() }]),
    )

    const last = events.at(-1)
    expect(last?.type === 'turn_complete' && last.envelope.answer).toBe('已为你查询库存告警')
    expect(last?.type === 'turn_complete' && last.envelope.analysisSources).toEqual([
      { source: 'DATABASE', degraded: false, degradedReason: null },
    ])
  })

  it('error 事件作为终止事件产出，不抛中断错误', async () => {
    const error = {
      code: 'DATA_SOURCE_UNAVAILABLE',
      message: 'boom',
      request_id: 'r-1',
      details: [],
      retryable: true,
    }

    const events = await collect(encodeStream([{ event: 'error', data: error }]))

    expect(events).toEqual([{ type: 'error', error }])
  })

  it('流结束却没有 turn_complete 或 error 时抛中断错误', async () => {
    const bytes = encodeStream([{ event: 'tool_call', data: TOOL_CALL }])

    await expect(async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars -- 只关心迭代结束时的行为，不关心产出的事件本身
      for await (const _ of readMerchantChatStream(streamOf(bytes, [32]))) {
        // 消费完整个流才能触发「结束却没有终止事件」的检查。
      }
    }).rejects.toThrow(ChatStreamInterruptedError)
  })
})
