/**
 * Adapter 契约测试。
 *
 * 载荷全部来自 `docs/fixtures/chat/`——那是后端从真实 `FakeAgent` 导出的输出。
 * 不在这里自造载荷：类型只保证字段名，保证不了语义组合，自造等于自己批改自己的
 * 作业（见 `scripts/export_chat_fixtures.py` 的说明）。
 */
import chatGreeting from '@fixtures/chat/chat-greeting.json'
import invalidRefused from '@fixtures/chat/invalid-refused.json'
import metricGmv from '@fixtures/chat/metric-gmv.json'
import detailOrder from '@fixtures/chat/detail-order.json'
import metricRefund from '@fixtures/chat/metric-refund.json'
import rulePlatform from '@fixtures/chat/rule-platform.json'
import { describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'

import { ChatContractError, toChatAnswer } from './chat'

type RawChatResponse = components['schemas']['ChatResponse']

const refund = metricRefund as RawChatResponse
const gmv = metricGmv as RawChatResponse
const orderDetail = detailOrder as RawChatResponse
const rule = rulePlatform as RawChatResponse
const greeting = chatGreeting as RawChatResponse
const refused = invalidRefused as RawChatResponse

describe('toChatAnswer · 真实载荷', () => {
  it('把 snake_case 映射成领域模型', () => {
    const answer = toChatAnswer(refund)

    expect(answer.id).toBe(refund.id)
    expect(answer.sessionId).toBe(refund.session_id)
    expect(answer.mode).toBe('METRIC')
    expect(answer.category).toBe('REFUND')
    expect(answer.answer).toContain('B4')
  })

  it('METRIC 的指标口径八字段完整映射', () => {
    const metric = toChatAnswer(refund).metric

    expect(metric).toEqual({
      code: 'return_count',
      displayName: '退货量',
      unit: '件',
      definition: '统计周期内创建的有效退货退款单数量。',
      source: 'Borough 指标目录',
      owner: '经营分析组',
      status: 'ACTIVE',
    })
  })

  it('B4 的 METRIC 携带真实查询到的数据行', () => {
    const answer = toChatAnswer(gmv)

    expect(answer.data?.rows).toEqual([{ gmv: '128000.50' }])
    expect(answer.data?.totalRows).toBe(1)
    expect(answer.data?.truncated).toBe(false)
    expect(answer.data?.queryPlan).toBeTruthy()
    // 图表仍是 B5 的工作：B4 只保证契约必填字段有值，不据真实数据生成图表。
    expect(answer.chart?.enabled).toBe(false)
    expect(answer.chart?.data).toHaveLength(0)
  })

  it('订单明细场景携带真实数据行', () => {
    const answer = toChatAnswer(orderDetail)

    expect(answer.mode).toBe('DETAIL')
    expect(answer.data?.totalRows).toBe(2)
    expect(answer.data?.truncated).toBe(false)
    expect(answer.data?.rows).toHaveLength(2)
    expect(answer.export).toBeDefined()
  })

  it('建议逐条映射，保留 evidence 与 action', () => {
    const recommendations = toChatAnswer(refund).recommendations

    expect(recommendations).toHaveLength(2)
    expect(recommendations[0]).toMatchObject({
      title: expect.any(String),
      evidence: expect.stringContaining('B3'),
      action: expect.stringContaining('B4'),
    })
  })

  it('真实数据查询成功后不再降级，来源标记为 DATABASE', () => {
    const quality = toChatAnswer(refund).quality

    expect(quality.degraded).toBe(false)
    expect(quality.degradedReason).toBeUndefined()
    expect(quality.sources).toEqual(['DATABASE'])
    expect(quality.status).toBe('NOT_RUN')
    expect(quality.attempts).toBe(0)
    expect(quality.notes.length).toBeGreaterThan(0)
  })

  it('猜你想问带当前组与备选组', () => {
    const suggestions = toChatAnswer(refund).suggestions

    expect(suggestions.current).toHaveLength(3)
    expect(suggestions.current[0]).toContain('退款')
    expect(suggestions.alternates).toHaveLength(1)
    expect(suggestions.alternates[0]).not.toEqual(suggestions.current)
  })

  it('思考步骤同构且不含内部实现细节', () => {
    const steps = toChatAnswer(gmv).thinkingSteps

    expect(steps.length).toBeGreaterThan(0)
    for (const step of steps) {
      expect(Object.keys(step).sort()).toEqual(['label', 'node'])
      expect(step.label).not.toMatch(/SELECT|Doris|数据库/)
    }
  })
})

describe('toChatAnswer · 无数据模式不被编造默认值填充', () => {
  it('RULE 没有指标、数据和图表', () => {
    const answer = toChatAnswer(rule)

    expect(answer.mode).toBe('RULE')
    expect(answer.category).toBe('PLATFORM_RULE')
    expect(answer.metric).toBeUndefined()
    expect(answer.data).toBeUndefined()
    expect(answer.chart).toBeUndefined()
    expect(answer.recommendations).toEqual([])
  })

  it('CHAT 是无来源回答', () => {
    const answer = toChatAnswer(greeting)

    expect(answer.mode).toBe('CHAT')
    expect(answer.category).toBe('UNKNOWN')
    expect(answer.metric).toBeUndefined()
    expect(answer.data).toBeUndefined()
    expect(answer.recommendations).toEqual([])
    expect(answer.quality.sources).toEqual(['NONE'])
    expect(answer.quality.degraded).toBe(false)
    expect(answer.quality.degradedReason).toBeUndefined()
  })

  it('INVALID 同样不带数据', () => {
    const answer = toChatAnswer(refused)

    expect(answer.mode).toBe('INVALID')
    expect(answer.data).toBeUndefined()
    expect(answer.quality.sources).toEqual(['NONE'])
  })
})

describe('toChatAnswer · 语义守卫', () => {
  const clone = (patch: Partial<RawChatResponse>): RawChatResponse => ({ ...refund, ...patch })

  it('拒绝空回答', () => {
    expect(() => toChatAnswer(clone({ answer: '   ' }))).toThrow(ChatContractError)
  })

  it('拒绝枚举外的 answer_mode', () => {
    const bad = clone({ answer_mode: 'SOMETHING_ELSE' as RawChatResponse['answer_mode'] })
    expect(() => toChatAnswer(bad)).toThrow(ChatContractError)
  })

  it('拒绝空的 analysis_sources', () => {
    expect(() => toChatAnswer(clone({ analysis_sources: [] }))).toThrow(ChatContractError)
  })

  it('CHAT 必须且只能是 NONE', () => {
    const bad = { ...greeting, analysis_sources: ['DATABASE'] } as RawChatResponse
    expect(() => toChatAnswer(bad)).toThrow(/NONE/)
  })

  it('CHAT 在 LLM 不可用时可显式降级', () => {
    const degraded = {
      ...greeting,
      degraded: true,
      degraded_reason: 'LLM 未配置或暂不可用',
      quality_status: 'DEGRADED',
      analysis_sources: ['FALLBACK'],
    } as RawChatResponse
    expect(toChatAnswer(degraded).quality.degraded).toBe(true)
  })

  it('降级的 CHAT 只能使用 FALLBACK 来源', () => {
    const bad = {
      ...greeting,
      degraded: true,
      degraded_reason: 'LLM 未配置或暂不可用',
      quality_status: 'DEGRADED',
    } as RawChatResponse
    expect(() => toChatAnswer(bad)).toThrow(/FALLBACK/)
  })

  it('含 FALLBACK 时必须降级', () => {
    const bad = clone({ analysis_sources: ['FALLBACK'], degraded: false, degraded_reason: null })
    expect(() => toChatAnswer(bad)).toThrow(/FALLBACK/)
  })

  it('降级必须给出原因', () => {
    const bad = clone({ analysis_sources: ['FALLBACK'], degraded: true, degraded_reason: null })
    expect(() => toChatAnswer(bad)).toThrow(ChatContractError)
  })

  it('METRIC 缺指标字段时报错', () => {
    expect(() => toChatAnswer(clone({ metric_owner: null }))).toThrow(/metric/i)
  })

  it('METRIC 缺图表时报错', () => {
    expect(() => toChatAnswer(clone({ visualization: null }))).toThrow(ChatContractError)
  })

  it('quality_attempts 超出 0–2 时报错', () => {
    expect(() => toChatAnswer(clone({ quality_attempts: 3 }))).toThrow(ChatContractError)
    expect(() => toChatAnswer(clone({ quality_attempts: -1 }))).toThrow(ChatContractError)
  })

  it('错误信息是中文，可直接展示', () => {
    try {
      toChatAnswer(clone({ answer: '' }))
      expect.unreachable('应当抛出 ChatContractError')
    } catch (error) {
      expect((error as Error).message).toMatch(/[一-龥]/)
    }
  })
})
