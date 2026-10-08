import type { MessageKey } from '@/i18n/messages'

/**
 * 首页快捷提问（PRD C1，D-N5-4）：对外演示只从商家端进入，访客经「顾客视角」来到首页，
 * 这几条要把顾客端 Agent 的主要能力带出来——五个顾客 Skill 各一条，加一条平台规则问答。
 *
 * 只是固定文案：点击把这句话原样发给助手，回答照常走工具循环与闸门，不预置答案（R7）。
 * 文案里的商品与规则都对应演示店铺的真实数据（`backend/app/analytics/demo_data.py`、
 * 知识库「退货」业务域），改文案前先核对种子数据。
 */
export type QuickPromptCapability =
  | 'search-discovery'
  | 'purchase-research'
  | 'planning-goals'
  | 'after-sales-service'
  | 'memory-personalization'
  | 'platform-rules'

export interface QuickPrompt {
  key: MessageKey
  capability: QuickPromptCapability
  icon: string
}

export const QUICK_PROMPTS: readonly QuickPrompt[] = [
  { key: 'home.quick1', capability: 'search-discovery', icon: '⌕' },
  { key: 'home.quick2', capability: 'purchase-research', icon: '⇄' },
  { key: 'home.quick3', capability: 'planning-goals', icon: '◇' },
  { key: 'home.quick4', capability: 'after-sales-service', icon: '↺' },
  { key: 'home.quick5', capability: 'memory-personalization', icon: '✎' },
  { key: 'home.quick6', capability: 'platform-rules', icon: '§' },
]
