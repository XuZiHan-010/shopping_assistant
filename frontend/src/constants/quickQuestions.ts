import type { SupportedLocale } from '@/i18n'

export interface QuickQuestion {
  readonly category: string
  readonly question: string
}

/**
 * 欢迎卡片的产品入口；不依赖 Mock 或后端返回。
 *
 * 这个常量本身**不改名、不改形状**——`api/mock/scenarios.ts`（Task 11 的
 * 职责范围）用它的中文问题字面量当类型和运行时 key 去匹配 Mock 场景，
 * 改成函数或换掉具体文案会直接破坏那个文件。Mock 场景匹配目前还是纯中文
 * 关键词（`api/mock/scenarios.ts` 的 `keywords`），Task 11 才会让它认识
 * 英文问题；因此英语界面下点击下面 `quickQuestions('en-US')` 给出的英文
 * 问题，目前仍会落到 Mock 的兜底闲聊场景，这是已知且已登记的过渡态。
 */
export const QUICK_QUESTIONS = [
  { category: '趋势分析', question: '最近7天退货量趋势' },
  { category: '经营指标', question: '昨天总 GMV 是多少？' },
  { category: '业务明细', question: '查看最近订单明细' },
  { category: '规则问答', question: '我要货品上架，具体规则有吗？' },
] as const satisfies readonly QuickQuestion[]

const QUICK_QUESTIONS_EN: readonly QuickQuestion[] = [
  { category: 'Trend analysis', question: 'What is the return trend over the last 7 days?' },
  { category: 'Business metric', question: "What was yesterday's total GMV?" },
  { category: 'Business detail', question: 'Show me the most recent order details' },
  { category: 'Rules & policies', question: 'What are the rules for listing a new product?' },
]

const QUICK_QUESTIONS_BY_LOCALE: Readonly<Record<SupportedLocale, readonly QuickQuestion[]>> = {
  'zh-CN': QUICK_QUESTIONS,
  'en-US': QUICK_QUESTIONS_EN,
}

/** 按当前展示语言取欢迎卡片的快速问题列表。 */
export function quickQuestions(locale: SupportedLocale): readonly QuickQuestion[] {
  return QUICK_QUESTIONS_BY_LOCALE[locale]
}
