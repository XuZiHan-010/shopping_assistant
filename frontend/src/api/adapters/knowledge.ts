import type { components } from '@/api/generated'

type RawKnowledgeTreeNode = components['schemas']['KnowledgeTreeNode']
type RawKnowledgeDocument = components['schemas']['KnowledgeDocumentResponse']

export interface KnowledgeTreeNode {
  name: string
  path: string
  nodeType: 'directory' | 'document'
  readOnly: boolean
  size: number
  version: string
  children: KnowledgeTreeNode[]
}

export interface KnowledgeDocument {
  path: string
  content: string
  readOnly: boolean
  version: string
}

export function toKnowledgeTree(
  response: components['schemas']['KnowledgeTreeResponse'],
): KnowledgeTreeNode[] {
  return response.roots.map(toKnowledgeTreeNode)
}

export function toKnowledgeDocument(raw: RawKnowledgeDocument): KnowledgeDocument {
  return {
    path: raw.path,
    content: raw.content,
    readOnly: raw.read_only,
    version: raw.version,
  }
}

function toKnowledgeTreeNode(raw: RawKnowledgeTreeNode): KnowledgeTreeNode {
  return {
    name: raw.name,
    path: raw.path,
    nodeType: raw.node_type,
    readOnly: raw.read_only,
    size: raw.size,
    version: raw.version,
    children: (raw.children ?? []).map(toKnowledgeTreeNode),
  }
}
