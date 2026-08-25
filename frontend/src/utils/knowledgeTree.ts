import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'

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
