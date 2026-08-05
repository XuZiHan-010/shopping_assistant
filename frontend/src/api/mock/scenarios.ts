/**
 * 演示场景。问题文本 → fixture 键。
 *
 * 快速问题必须能命中 fixture，否则点了没反应——F2 验收「每个快速问题均可完成
 * 一轮问答」正是靠这个成立。问题文本取自 docs/fixtures/chat/README.md 记录的
 * 触发问题，与后端 FakeAgent 的判定一致。
 */
import type { components } from '@/api/generated'

import type { ChatFixtureKey } from './fixtures.generated'

interface Scenario {
  question: string
  fixture: ChatFixtureKey
  /** 命中该场景的关键词，任一出现即匹配。 */
  keywords: readonly string[]
  /**
   * 快速体验区的分类眉标。只有带 category 的场景才会出现在入口里——
   * `chatGreeting` 是兜底、`invalidRefused` 是「助手会拒绝」的场景，
   * **都不该被主动推荐**：推荐一个设计上就要被拒的请求，等于教用户去踩线。
   */
  category?: string
}

export const MOCK_SCENARIOS: readonly Scenario[] = [
  {
    question: '最近7天退货量趋势',
    fixture: 'metricRefund',
    keywords: ['退货', '退款'],
    category: '趋势分析',
  },
  {
    question: '昨天总 GMV 是多少？',
    fixture: 'metricGmv',
    keywords: ['gmv', '成交额'],
    category: '经营指标',
  },
  {
    question: '查看最近订单明细',
    fixture: 'detailOrder',
    keywords: ['明细', '订单列表'],
    category: '业务明细',
  },
  {
    question: '我要货品上架，具体规则有吗？',
    fixture: 'rulePlatform',
    keywords: ['规则', '上架', '政策'],
    category: '规则问答',
  },
  { question: '你好', fixture: 'chatGreeting', keywords: ['你好', '在吗', '介绍'] },
  {
    question: '帮我修改订单金额',
    fixture: 'invalidRefused',
    keywords: ['修改订单', '改金额', '删除数据'],
  },
  {
    // IDENTITY 仍是 B4 未接入的受控空结果（商家资料查询留给后续阶段），刻意不给
    // category：和 chatGreeting/invalidRefused 一样，不该被主动推荐去踩一个
    // 明知会降级的场景，但仍需可达——它是目前唯一还能演示「FALLBACK 必须可见」
    // （R7）的固定场景。
    question: '我的商家资料是什么？',
    fixture: 'identityProfile',
    keywords: ['商家资料', '身份信息'],
  },
] as const

/** 快速体验入口。顺序与分类对齐 Prototype 的四宫格。 */
export const MOCK_QUICK_QUESTIONS = MOCK_SCENARIOS.filter(
  (scenario): scenario is Scenario & { category: string } => Boolean(scenario.category),
).map((scenario) => ({ question: scenario.question, category: scenario.category }))

/** 没命中任何关键词时回落到闲聊，与后端 FakeAgent 的兜底一致。 */
export function matchScenario(message: string): ChatFixtureKey {
  const text = message.toLowerCase()
  const hit = MOCK_SCENARIOS.find(
    (scenario) =>
      scenario.question.toLowerCase() === text ||
      scenario.keywords.some((keyword) => text.includes(keyword)),
  )
  return hit?.fixture ?? 'chatGreeting'
}

export const MOCK_MERCHANTS: readonly components['schemas']['DemoMerchant'][] = [
  { merchant_id: 'merchant-100', display_name: 'Borough商家100', token: 'demo-token-100' },
  { merchant_id: 'merchant-101', display_name: 'Borough商家101', token: 'demo-token-101' },
  { merchant_id: 'merchant-102', display_name: 'Borough商家102', token: 'demo-token-102' },
] as const
