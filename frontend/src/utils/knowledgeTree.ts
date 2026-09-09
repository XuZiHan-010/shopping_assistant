import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'
import type { SupportedLocale } from '@/i18n'

/**
 * 与后端 `BUSINESS_SECTIONS`（`backend/app/knowledge/path_policy.py`）逐字一致的固定板块名。
 * 只有这四个板块下才允许新建文档，业务域根目录本身不能直接挂文档。
 */
export const BUSINESS_SECTIONS = [
  '业务流程',
  '业务名词解释',
  'ddl',
  '指标或调用指标平台mcp的skill',
] as const

export function isBusinessDomain(node: KnowledgeTreeNode | undefined): boolean {
  if (!node || node.readOnly || node.nodeType !== 'directory') return false
  const parts = node.path.split('/')
  return parts.length === 2 && parts[0] === '业务'
}

export function isDocumentParent(node: KnowledgeTreeNode | undefined): boolean {
  if (!node || node.readOnly || node.nodeType !== 'directory') return false
  if (node.path === 'index') return true
  const parts = node.path.split('/')
  return (
    parts.length === 3 &&
    parts[0] === '业务' &&
    (BUSINESS_SECTIONS as readonly string[]).includes(parts[2])
  )
}

export function canDeleteNode(node: KnowledgeTreeNode | undefined): boolean {
  if (!node || node.readOnly) return false
  return node.nodeType === 'document' || isBusinessDomain(node)
}

export function findNode(roots: KnowledgeTreeNode[], path: string): KnowledgeTreeNode | undefined {
  for (const node of roots) {
    if (node.path === path) return node
    const found = findNode(node.children, path)
    if (found) return found
  }
  return undefined
}

function isBusinessSectionNode(node: KnowledgeTreeNode): boolean {
  const parts = node.path.split('/')
  return (
    parts.length === 3 &&
    parts[0] === '业务' &&
    (BUSINESS_SECTIONS as readonly string[]).includes(parts[2])
  )
}

/**
 * 固定板块名的中 → 英展示映射，与 `BUSINESS_SECTIONS` 逐项对应。
 */
const SECTION_DISPLAY_NAMES_EN: Readonly<Record<string, string>> = {
  业务流程: 'Business process',
  业务名词解释: 'Business glossary',
  ddl: 'DDL',
  指标或调用指标平台mcp的skill: 'Metrics & MCP skill',
}

/**
 * 演示知识库随产品发布、固定 shipped 的业务域集合（`backend/app/knowledge/
 * wiki_seed.json` 里 `业务/<域>/...` 的全部 10 个二级目录名），与
 * `constants/quickQuestions.ts`/`constants/columnLabels.ts` 同属「已知闭集
 * 才翻译」的原则：管理员在后台新建的业务域名称是自由文本，不在这张表里的
 * 名称原样展示，不臆造译名。
 */
const KNOWN_DOMAIN_DISPLAY_NAMES_EN: Readonly<Record<string, string>> = {
  交易: 'Trade',
  优惠券: 'Coupons',
  供应链: 'Supply chain',
  商品: 'Products',
  商家其他: 'Merchant other',
  客服工单: 'Customer service tickets',
  平台规则: 'Platform rules',
  理赔赔付: 'Compensation & claims',
  身份信息: 'Identity information',
  退货: 'Returns',
}

/**
 * 知识库目录树节点的展示名称。稳定 `path`（用于选中、匹配、请求）永远保持
 * 后端原值不变；本函数只影响 `KnowledgeTree.vue` 渲染出来的文字。
 *
 * 中文模式或节点不在已知闭集内时原样返回 `node.name`——本函数不做机器翻译，
 * 也不臆造管理员自由创建的业务域/文档名称的英文译名。
 */
export function displayNodeName(node: KnowledgeTreeNode, locale: SupportedLocale): string {
  if (locale !== 'en-US') return node.name
  if (node.path === '业务') return 'Business'
  if (isBusinessDomain(node) && node.name in KNOWN_DOMAIN_DISPLAY_NAMES_EN) {
    return KNOWN_DOMAIN_DISPLAY_NAMES_EN[node.name]
  }
  if (isBusinessSectionNode(node) && node.name in SECTION_DISPLAY_NAMES_EN) {
    return SECTION_DISPLAY_NAMES_EN[node.name]
  }
  return node.name
}
