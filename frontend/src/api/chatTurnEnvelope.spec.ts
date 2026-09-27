import { describe, expect, it } from 'vitest'

import { parseFinalResponse, toTurnView, type RawFinalResponse } from './chatTurnEnvelope'

/** v1 `ChatResponse.analysis_sources` 是纯字符串数组，没有逐来源降级信息。 */
function rawV1FinalResponse(overrides: Partial<RawFinalResponse> = {}): RawFinalResponse {
  return {
    answer: '这是回答正文',
    analysis_sources: ['DATABASE'],
    thinking_steps: [{ label: '查询数据', node: 'query' }],
    quality_status: 'PASSED',
    quality_attempts: 1,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
    ...overrides,
  }
}

/** v2 `MerchantChatResponse.analysis_sources` 是 `AnalysisSourceEntry[]`，逐来源带降级状态。 */
function rawV2FinalResponse(overrides: Partial<RawFinalResponse> = {}): RawFinalResponse {
  return {
    answer: '这是回答正文',
    analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
    thinking_steps: [{ label: '查询数据', node: 'query' }],
    quality_status: 'PASSED',
    quality_attempts: 1,
    quality_notes: [],
    degraded: false,
    degraded_reason: null,
    ...overrides,
  }
}

describe('parseFinalResponse', () => {
  it('v1 载荷（analysis_sources 是纯字符串数组）解析出的来源没有逐项降级信息', () => {
    const envelope = parseFinalResponse(rawV1FinalResponse())

    expect(envelope.answer).toBe('这是回答正文')
    expect(envelope.analysisSources).toEqual([
      { source: 'DATABASE', degraded: false, degradedReason: null },
    ])
    expect(envelope.thinkingSteps).toEqual([{ label: '查询数据', node: 'query' }])
    expect(envelope.qualityStatus).toBe('PASSED')
    expect(envelope.degraded).toBe(false)
  })

  it('v2 载荷（analysis_sources 是 AnalysisSourceEntry[]）保留逐来源降级信息', () => {
    const envelope = parseFinalResponse(
      rawV2FinalResponse({
        analysis_sources: [
          { source: 'KNOWLEDGE', degraded: true, degraded_reason: '知识库暂时不可用' },
        ],
      }),
    )

    expect(envelope.analysisSources).toEqual([
      { source: 'KNOWLEDGE', degraded: true, degradedReason: '知识库暂时不可用' },
    ])
  })

  it('v2 载荷带着 v1 没有的字段（如 tool_calls）时，公共字段仍解析出同样的 envelope', () => {
    const v1Envelope = parseFinalResponse(rawV1FinalResponse())
    const v2Raw: RawFinalResponse & Record<string, unknown> = {
      ...rawV2FinalResponse(),
      id: 'msg-1',
      conversation_id: 'conv-1',
      tool_calls: [
        {
          tool_name: 'get_inventory_alerts',
          call_id: 'c1',
          status: 'SUCCEEDED',
          summary: '处理完成',
        },
      ],
      answer_mode: 'CHAT',
    }
    const v2Envelope = parseFinalResponse(v2Raw)

    // 两者字段集合不同（tool_calls 只在 v2 出现），但走的是同一个解析函数，
    // 且公共子集（answer/来源/质量/降级）解析结果完全一致。
    expect(v2Envelope).toEqual(v1Envelope)
  })

  it('thinking_steps / quality_notes 缺省为空数组，不是 undefined', () => {
    const envelope = parseFinalResponse(
      rawV1FinalResponse({ thinking_steps: undefined, quality_notes: undefined }),
    )

    expect(envelope.thinkingSteps).toEqual([])
    expect(envelope.qualityNotes).toEqual([])
  })
})

describe('toTurnView', () => {
  it('单来源降级不把整轮标为降级', () => {
    const envelope = parseFinalResponse(
      rawV2FinalResponse({
        degraded: false,
        analysis_sources: [
          { source: 'DATABASE', degraded: false, degraded_reason: null },
          { source: 'KNOWLEDGE', degraded: true, degraded_reason: '知识库暂时不可用' },
        ],
      }),
    )

    const view = toTurnView(envelope)

    expect(view.turnDegraded).toBe(false)
    expect(view.sources.find((s) => s.source === 'KNOWLEDGE')?.degraded).toBe(true)
  })

  it('整轮降级时 turnDegraded 为 true', () => {
    const envelope = parseFinalResponse(
      rawV2FinalResponse({ degraded: true, degraded_reason: '数据源暂时不可用' }),
    )

    expect(toTurnView(envelope).turnDegraded).toBe(true)
  })
})
