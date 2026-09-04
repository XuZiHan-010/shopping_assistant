/**
 * Adapter 契约测试。
 *
 * 载荷全部来自 `docs/fixtures/chat/`——那是后端从真实 `FakeAgent` 导出的输出。
 * 不在这里自造载荷：类型只保证字段名，保证不了语义组合，自造等于自己批改自己的
 * 作业（见 `scripts/export_chat_fixtures.py` 的说明）。
 */
import chatGreeting from '@fixtures/chat/chat-greeting.json'
import identityProfile from '@fixtures/chat/identity-profile.json'
import invalidRefused from '@fixtures/chat/invalid-refused.json'
import metricGmv from '@fixtures/chat/metric-gmv.json'
import detailOrder from '@fixtures/chat/detail-order.json'
import metricRefund from '@fixtures/chat/metric-refund.json'
import rulePlatform from '@fixtures/chat/rule-platform.json'
import { describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'

import {
  ChatContractError,
  toChatAnswer,
  toConversationAnswer,
  toFeedbackRequestPayload,
  toFeedbackState,
} from './chat'

type RawChatResponse = components['schemas']['ChatResponse']

const refund = metricRefund as RawChatResponse
const gmv = metricGmv as RawChatResponse
const orderDetail = detailOrder as RawChatResponse
const rule = rulePlatform as RawChatResponse
const greeting = chatGreeting as RawChatResponse
const refused = invalidRefused as RawChatResponse
const identity = identityProfile as RawChatResponse

/**
 * 双语契约测试专用的翻译模拟（Task 12 Step 4）。
 *
 * `docs/fixtures/chat/*.json` 固定是源语言（中文）——真实的中英文差异只在
 * 运行时由后端翻译服务产生，导出脚本不模拟翻译（见 `mock/scenarios.ts` 顶部
 * 同一结论）。这里手工构造一份"假想已被翻译成英文"的载荷，只改人类可读的
 * 文本字段，技术字段（id、枚举、编号、布尔、数值、URL）原样保留，从而验证
 * Adapter 的 snake_case → camelCase 转换和"技术字段不受本地化影响"这两件事
 * 在中英文载荷下都成立——Adapter 本身不做任何翻译，只做结构转换。
 */
function toEnglishRaw(raw: RawChatResponse): RawChatResponse {
  const en = (value: string) => `EN: ${value}`
  const enOrNull = (value: string | null | undefined) =>
    value == null ? value : en(value)

  return {
    ...raw,
    answer: raw.answer ? en(raw.answer) : raw.answer,
    displayed_user_message: raw.displayed_user_message
      ? en(raw.displayed_user_message)
      : raw.displayed_user_message,
    degraded_reason: enOrNull(raw.degraded_reason),
    quality_notes: (raw.quality_notes ?? []).map(en),
    suggestions: (raw.suggestions ?? []).map(en),
    suggestion_alternates: (raw.suggestion_alternates ?? []).map((group) => group.map(en)),
    recommendations: raw.recommendations
      ? raw.recommendations.map((item) => ({
          ...item,
          title: en(item.title),
          evidence: en(item.evidence),
          action: en(item.action),
        }))
      : raw.recommendations,
    thinking_steps: (raw.thinking_steps ?? []).map((step) => ({ ...step, label: en(step.label) })),
    metric_display_name: enOrNull(raw.metric_display_name),
    metric_definition: enOrNull(raw.metric_definition),
    metric_notice: enOrNull(raw.metric_notice),
    query_plan: raw.query_plan ? { ...raw.query_plan, summary: en(raw.query_plan.summary) } : raw.query_plan,
  }
}

describe('toChatAnswer · 真实载荷', () => {
  it('把 snake_case 映射成领域模型', () => {
    const answer = toChatAnswer(refund)

    expect(answer.id).toBe(refund.id)
    expect(answer.sessionId).toBe(refund.session_id)
    expect(answer.mode).toBe('METRIC')
    expect(answer.category).toBe('REFUND')
    expect(answer.answer).toContain('受控数据查询')
    expect(answer.contractWarnings).toEqual([])
  })

  it('displayed_user_message 映射为 displayedUserMessage（Task 11）', () => {
    const answer = toChatAnswer({ ...refund, displayed_user_message: '昨天的退货量趋势如何？' })

    expect(answer.displayedUserMessage).toBe('昨天的退货量趋势如何？')
  })

  it('displayed_user_message 为空串时原样传递，不抛契约错误', () => {
    // `refund` 这份由后端导出脚本生成的真实 fixture里，该字段本身就是空串
    // （导出脚本的 stub 上下文没有真实用户提问文本）——空串是合法取值，不是
    // 字段缺失,不需要额外构造缺字段的载荷。
    const answer = toChatAnswer(refund)

    expect(answer.displayedUserMessage).toBe('')
  })

  it('METRIC 的指标口径八字段完整映射', () => {
    const metric = toChatAnswer(refund).metric

    expect(metric).toEqual({
      code: 'return_count',
      displayName: '退货量',
      unit: '件',
      definition: '统计周期内创建的有效退货退款单数量。',
      sqlDefinition: '',
      dimensions: [],
      sourceDatabase: '',
      sourceTable: '',
      source: 'METRIC_CATALOG',
      generated: false,
      owner: '经营分析组',
      status: 'ACTIVE',
    })
  })

  it('B5 的 METRIC 返回可渲染的受控图表数据', () => {
    const answer = toChatAnswer(gmv)

    expect(answer.data?.rows).toHaveLength(1)
    expect(answer.data?.totalRows).toBe(1)
    expect(answer.data?.truncated).toBe(false)
    expect(answer.data?.queryPlan).toBeTruthy()
    expect(answer.chart?.enabled).toBe(true)
    expect(answer.chart?.data).toHaveLength(1)
    expect(answer.chart?.dimensionKey).toBe('date')
    expect(answer.chart?.metricKey).toBe('gmv')
  })

  it('订单明细场景保留截断信息', () => {
    const answer = toChatAnswer(orderDetail)

    expect(answer.mode).toBe('DETAIL')
    expect(answer.data?.totalRows).toBe(2)
    expect(answer.data?.truncated).toBe(false)
    expect(answer.data?.rows).toHaveLength(2)
    expect(answer.export).toBeDefined()
  })

  it('建议逐条映射，保留 evidence 与 action', () => {
    const recommendations = toChatAnswer(gmv).recommendations

    expect(recommendations).toHaveLength(2)
    expect(recommendations[0]).toMatchObject({
      title: expect.any(String),
      evidence: '结果来自已校验的商家范围。',
      action: '结合业务背景确认筛选条件。',
    })
  })

  it('质量轨迹字段完整映射', () => {
    const quality = toChatAnswer(gmv).quality

    expect(quality.degraded).toBe(false)
    expect(quality.degradedReason).toBeUndefined()
    expect(quality.sources).toEqual(['DATABASE'])
    expect(quality.status).toBe('PASSED')
    expect(quality.attempts).toBe(1)
    expect(quality.notes).toEqual(gmv.quality_notes ?? [])
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

  it('接受仅含表格的空正文 DETAIL，并保留导出与行数', () => {
    const tableOnly = {
      ...orderDetail,
      answer: '',
      recommendations: [],
    } as RawChatResponse

    const answer = toChatAnswer(tableOnly)

    expect(answer.answer).toBe('')
    expect(answer.mode).toBe('DETAIL')
    expect(answer.data?.totalRows).toBe(2)
    expect(answer.export?.url).toBe(orderDetail.export?.url)
    expect(answer.recommendations).toEqual([])
  })

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
    const bad = clone({
      analysis_sources: ['FALLBACK'] as RawChatResponse['analysis_sources'],
      degraded: false,
      degraded_reason: null,
    })
    expect(() => toChatAnswer(bad)).toThrow(/FALLBACK/)
  })

  it('降级必须给出原因', () => {
    const bad = clone({ degraded: true, degraded_reason: null })
    expect(() => toChatAnswer(bad)).toThrow(ChatContractError)
  })

  it('METRIC 缺按模式字段时降级而非抛异常', () => {
    const raw = clone({ metric_owner: null })
    const answer = toChatAnswer(raw)

    expect(answer.metric).toBeUndefined()
    expect(answer.contractWarnings).toHaveLength(1)
    expect(answer.contractWarnings[0]).toContain('metric_owner')
    expect(answer.answer.length).toBeGreaterThan(0) // 正文照常可读
  })

  it('METRIC 缺图表时降级而非抛异常', () => {
    const raw = clone({ visualization: null })
    const answer = toChatAnswer(raw)

    expect(answer.chart).toBeUndefined()
    expect(answer.contractWarnings).toEqual(['METRIC 回答缺少 visualization，图表面板将显示空状态'])
  })

  it('不把非 HTTP/HTTPS 的报表链接交给面板渲染', () => {
    const answer = toChatAnswer(clone({ metric_report_url: 'javascript:alert(1)' }))

    expect(answer.metric?.reportUrl).toBeUndefined()
    expect(answer.contractWarnings).toContain(
      'metric_report_url 不是安全的 HTTP/HTTPS 绝对链接，已隐藏。',
    )
  })

  it('语义不变量违反时仍然抛 CONTRACT', () => {
    const raw = clone({ degraded: true, degraded_reason: null })
    expect(() => toChatAnswer(raw)).toThrow(expect.objectContaining({ code: 'CONTRACT' }))
  })

  it('quality_attempts 超出 0–3 时报错', () => {
    expect(toChatAnswer(clone({ quality_attempts: 3 })).quality.attempts).toBe(3)
    expect(() => toChatAnswer(clone({ quality_attempts: 4 }))).toThrow(ChatContractError)
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

describe('toChatAnswer · 双语契约：zh-CN / en-US 各覆盖 6 种 answer_mode（Task 12 Step 4）', () => {
  const cases: Array<{ name: string; raw: RawChatResponse }> = [
    { name: 'METRIC(gmv)', raw: gmv },
    { name: 'METRIC(refund)', raw: refund },
    { name: 'DETAIL', raw: orderDetail },
    { name: 'RULE', raw: rule },
    { name: 'IDENTITY', raw: identity },
    { name: 'CHAT', raw: greeting },
    { name: 'INVALID', raw: refused },
  ]

  it.each(cases)(
    '$name：zh-CN 与 en-US 载荷都能正确转换 camelCase，且技术字段不受语言影响',
    ({ raw }) => {
      const zhAnswer = toChatAnswer(raw)
      const enRaw = toEnglishRaw(raw)
      const enAnswer = toChatAnswer(enRaw)

      // --- snake_case → camelCase 转换对双语载荷都成立 ---
      expect(enAnswer.mode).toBe(raw.answer_mode)
      expect(enAnswer.sessionId).toBe(raw.session_id)
      if (raw.answer) {
        expect(enAnswer.answer).toBe(`EN: ${raw.answer}`)
        expect(enAnswer.answer).not.toBe(zhAnswer.answer)
      }
      if (zhAnswer.thinkingSteps.length > 0) {
        expect(enAnswer.thinkingSteps).toHaveLength(zhAnswer.thinkingSteps.length)
        enAnswer.thinkingSteps.forEach((step, index) => {
          expect(step.label).toBe(`EN: ${zhAnswer.thinkingSteps[index].label}`)
          // node 是内部实现标识，不是给人看的文本，不参与本地化。
          expect(step.node).toBe(zhAnswer.thinkingSteps[index].node)
        })
      }
      if (zhAnswer.quality.notes.length > 0) {
        expect(enAnswer.quality.notes).toEqual(zhAnswer.quality.notes.map((note) => `EN: ${note}`))
      }
      if (zhAnswer.quality.degradedReason) {
        expect(enAnswer.quality.degradedReason).toBe(`EN: ${zhAnswer.quality.degradedReason}`)
      }
      if (zhAnswer.recommendations.length > 0) {
        enAnswer.recommendations.forEach((item, index) => {
          expect(item.title).toBe(`EN: ${zhAnswer.recommendations[index].title}`)
          expect(item.evidence).toBe(`EN: ${zhAnswer.recommendations[index].evidence}`)
          expect(item.action).toBe(`EN: ${zhAnswer.recommendations[index].action}`)
        })
      }
      if (zhAnswer.metric) {
        expect(enAnswer.metric?.displayName).toBe(`EN: ${zhAnswer.metric.displayName}`)
        expect(enAnswer.metric?.definition).toBe(`EN: ${zhAnswer.metric.definition}`)
      }

      // --- 技术字段：无论请求语言是什么，值必须逐字相同（不能被"翻译"）---
      expect(enAnswer.id).toBe(zhAnswer.id)
      expect(enAnswer.sessionId).toBe(zhAnswer.sessionId)
      expect(enAnswer.mode).toBe(zhAnswer.mode)
      expect(enAnswer.category).toBe(zhAnswer.category)
      expect(enAnswer.quality.status).toBe(zhAnswer.quality.status)
      expect(enAnswer.quality.attempts).toBe(zhAnswer.quality.attempts)
      expect(enAnswer.quality.sources).toEqual(zhAnswer.quality.sources)
      expect(enAnswer.quality.degraded).toBe(zhAnswer.quality.degraded)
      expect(enAnswer.contractWarnings).toHaveLength(zhAnswer.contractWarnings.length)
      expect(enAnswer.thinkingSteps.map((step) => step.node)).toEqual(
        zhAnswer.thinkingSteps.map((step) => step.node),
      )

      if (zhAnswer.metric) {
        expect(enAnswer.metric?.code).toBe(zhAnswer.metric.code)
        expect(enAnswer.metric?.unit).toBe(zhAnswer.metric.unit)
        expect(enAnswer.metric?.sqlDefinition).toBe(zhAnswer.metric.sqlDefinition)
        expect(enAnswer.metric?.sourceDatabase).toBe(zhAnswer.metric.sourceDatabase)
        expect(enAnswer.metric?.sourceTable).toBe(zhAnswer.metric.sourceTable)
        expect(enAnswer.metric?.source).toBe(zhAnswer.metric.source)
        expect(enAnswer.metric?.generated).toBe(zhAnswer.metric.generated)
        expect(enAnswer.metric?.status).toBe(zhAnswer.metric.status)
      } else {
        expect(enAnswer.metric).toBeUndefined()
      }

      if (zhAnswer.data) {
        expect(enAnswer.data?.totalRows).toBe(zhAnswer.data.totalRows)
        expect(enAnswer.data?.truncated).toBe(zhAnswer.data.truncated)
        expect(enAnswer.data?.rows).toEqual(zhAnswer.data.rows)
      } else {
        expect(enAnswer.data).toBeUndefined()
      }

      if (zhAnswer.chart) {
        expect(enAnswer.chart?.enabled).toBe(zhAnswer.chart.enabled)
        expect(enAnswer.chart?.dimensionKey).toBe(zhAnswer.chart.dimensionKey)
        expect(enAnswer.chart?.metricKey).toBe(zhAnswer.chart.metricKey)
        expect(enAnswer.chart?.data).toEqual(zhAnswer.chart.data)
      } else {
        expect(enAnswer.chart).toBeUndefined()
      }

      if (zhAnswer.export) {
        expect(enAnswer.export?.id).toBe(zhAnswer.export.id)
        expect(enAnswer.export?.url).toBe(zhAnswer.export.url)
      } else {
        expect(enAnswer.export).toBeUndefined()
      }
    },
  )
})

describe('toConversationAnswer · 会话详情的助手回答载荷', () => {
  it('不填 displayedUserMessage——content 是助手自己的回答正文，不是配对的用户消息', () => {
    const answer = toConversationAnswer(
      {
        answer_id: 'answer-1',
        answer_mode: 'CHAT',
        thinking_steps: [],
        quality_status: 'NOT_RUN',
        quality_attempts: 0,
        quality_notes: [],
        degraded: false,
        degraded_reason: null,
        is_adopted: false,
        reaction: null,
        columns: [],
        total_rows: null,
        truncated: null,
      },
      {
        sessionId: 'session-1',
        // 故意用一句明显是"助手回答"而不是"用户提问"的文本，防止将来有人
        // 把这个字段的值改回 content 又误以为测试通过了。
        content: '已完成结构化理解，这是助手的回答正文。',
        createdAt: '2026-08-01T00:00:00Z',
      },
    )

    expect(answer.answer).toBe('已完成结构化理解，这是助手的回答正文。')
    expect(answer.displayedUserMessage).toBeUndefined()
  })
})

describe('反馈契约转换', () => {
  it('请求把完整 camelCase 状态转换为 snake_case，且保留 null reaction', () => {
    expect(toFeedbackRequestPayload({ isAdopted: true, reaction: null })).toEqual({
      is_adopted: true,
      reaction: null,
    })
  })

  it('响应转换为领域状态', () => {
    expect(
      toFeedbackState({ answer_id: 'answer-1', is_adopted: false, reaction: 'DISLIKE' }),
    ).toEqual({ isAdopted: false, reaction: 'DISLIKE' })
  })

  it.each(['LIKE', 'DISLIKE'] as const)('%s 状态双向转换保持一致', (reaction) => {
    const state = { isAdopted: true, reaction }
    const request = toFeedbackRequestPayload(state)

    expect(
      toFeedbackState({
        answer_id: 'answer-1',
        is_adopted: request.is_adopted,
        reaction: request.reaction ?? null,
      }),
    ).toEqual(state)
  })
})
