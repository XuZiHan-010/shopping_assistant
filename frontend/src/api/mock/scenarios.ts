/**
 * 演示场景。问题文本 → fixture 键。
 *
 * 快速问题必须能命中 fixture，否则点了没反应——F2 验收「每个快速问题均可完成
 * 一轮问答」正是靠这个成立。问题文本取自 docs/fixtures/chat/README.md 记录的
 * 触发问题，与后端 FakeAgent 的判定一致。
 */
import type { components } from '@/api/generated'
import { QUICK_QUESTIONS } from '@/constants/quickQuestions'

import type { ChatFixtureKey } from './fixtures.generated'

interface Scenario {
  question: string
  fixture: ChatFixtureKey
  /** 命中该场景的关键词，任一出现即匹配。 */
  keywords: readonly string[]
}

const QUICK_SCENARIO_DETAILS: Record<
  (typeof QUICK_QUESTIONS)[number]['question'],
  Omit<Scenario, 'question'>
> = {
  最近7天退货量趋势: { fixture: 'metricRefund', keywords: ['退货', '退款'] },
  '昨天总 GMV 是多少？': { fixture: 'metricGmv', keywords: ['gmv', '成交额'] },
  查看最近订单明细: { fixture: 'detailOrder', keywords: ['明细', '订单列表'] },
  '我要货品上架，具体规则有吗？': { fixture: 'rulePlatform', keywords: ['规则', '上架', '政策'] },
}

export const MOCK_SCENARIOS: readonly Scenario[] = [
  ...QUICK_QUESTIONS.map((item) => ({
    ...item,
    ...QUICK_SCENARIO_DETAILS[item.question],
  })),
  { question: '你好', fixture: 'chatGreeting', keywords: ['你好', '在吗', '介绍'] },
  {
    question: '帮我修改订单金额',
    fixture: 'invalidRefused',
    keywords: ['修改订单', '改金额', '删除数据'],
  },
  {
    // 未带 category：IDENTITY 目前仍是受控空结果（降级），不该被主动推荐到四宫格，
    // 但要能被主动输入命中——它是唯一仍会触发「演示数据」降级提示的场景（R7）。
    question: '我的商家资料是什么？',
    fixture: 'identityProfile',
    keywords: ['商家资料', '店铺认证'],
  },
] as const

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

// ---------------------------------------------------------------------------
// 双语 Mock（Task 11 Step 8）
//
// 真实契约由后端 LLM 翻译服务按 Accept-Language 生成英文内容（Task 1-8）。
// `docs/fixtures/chat/*.json` 由 `scripts/export_chat_fixtures.py` 从 B3
// FakeAgent 导出，固定是源语言（中文）——它验证的是回答的**结构**（字段、
// 组合约束），不模拟翻译，Task 12 重新导出后依然如此，也不应该改变这一点。
// 这里用一张小词表 + 兜底前缀模拟"同一份 fixture 在不同语言下返回不同内容"
// 这件事本身——重点是让依赖 Accept-Language 分支的前端逻辑（transport 装配
// 头、mock 按头分流、Store 的 epoch/reload）能被 Mock 真实验证，而不是纵容
// 组件自己临时翻译。词表覆盖当前 6 个 fixture 复用的固定思考步骤标签（逐字
// 对应 `backend/app/agent` 的节点标签）与演示问题文案；命中不到的自由文本
// 一律加 `[en] ` 前缀，不伪装成真翻译。
// ---------------------------------------------------------------------------

const MOCK_EN_DICTIONARY: Record<string, string> = {
  识别商家与会话上下文: 'Identify merchant and conversation context',
  读取业务知识索引: 'Read the business knowledge index',
  判定问题范围: 'Determine whether the question is in scope',
  识别问题类型与业务域: 'Classify the question type and business domain',
  结构化理解问题: 'Structure the question',
  校验查询意图: 'Validate the query intent',
  读取业务知识正文: 'Read the business knowledge content',
  查询经营数据: 'Query business data',
  整理回答: 'Compose the answer',
  校验并复核回答质量: 'Validate and review answer quality',
  生成推荐问题: 'Generate suggested questions',
  保存本轮回答: 'Persist this round of the answer',
  最近7天退货量趋势: 'Return trend over the last 7 days',
  '昨天总 GMV 是多少？': "What was yesterday's total GMV?",
  查看最近订单明细: 'View recent order details',
  '我要货品上架，具体规则有吗？': 'I want to list a product — what are the rules?',
  你好: 'Hello',
  帮我修改订单金额: 'Help me modify the order amount',
  '我的商家资料是什么？': 'What is my merchant profile?',
}

/**
 * 词表命中直接返回；未命中一律加 `[en] ` 前缀而不是原样返回中文——这样任何
 * 一处忘了走这个函数的字段都会在英文断言里露出中文原文，测试能立刻发现，
 * 不会被"反正长得差不多"糊弄过去。
 */
export function mockEnglishText(zh: string): string {
  return MOCK_EN_DICTIONARY[zh] ?? `[en] ${zh}`
}

const MOCK_MERCHANT_NAMES_EN: Record<string, string> = {
  Borough商家100: 'Borough Merchant 100',
  Borough商家101: 'Borough Merchant 101',
  Borough商家102: 'Borough Merchant 102',
}

export function mockEnglishMerchantName(displayName: string): string {
  return MOCK_MERCHANT_NAMES_EN[displayName] ?? displayName
}
