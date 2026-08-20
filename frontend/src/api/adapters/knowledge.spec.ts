import { describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'

import { toKnowledgeDocument, toKnowledgeTree } from './knowledge'

describe('知识库后台契约 Adapter', () => {
  it('完整映射目录树节点，并保留 read_only', () => {
    const raw = {
      roots: [
        {
          name: 'memory',
          path: 'memory',
          node_type: 'directory',
          read_only: true,
          size: 12,
          version: 'tree-v1',
          children: [],
        },
      ],
    } as components['schemas']['KnowledgeTreeResponse']

    expect(toKnowledgeTree(raw)).toEqual([
      {
        name: 'memory',
        path: 'memory',
        nodeType: 'directory',
        readOnly: true,
        size: 12,
        version: 'tree-v1',
        children: [],
      },
    ])
  })

  it('将生成契约中可选的 children 归一为空数组', () => {
    const raw = {
      roots: [
        {
          name: 'index',
          path: 'index',
          node_type: 'directory',
          read_only: false,
          size: 0,
          version: 'tree-v1',
        },
      ],
    } as components['schemas']['KnowledgeTreeResponse']

    expect(toKnowledgeTree(raw)[0]?.children).toEqual([])
  })

  it('完整映射文档并保留只读与版本', () => {
    const raw = {
      path: 'memory/merchants/a/TRADE.md',
      content: '自动沉淀内容',
      read_only: true,
      version: 'doc-v1',
    } as components['schemas']['KnowledgeDocumentResponse']

    expect(toKnowledgeDocument(raw)).toEqual({
      path: 'memory/merchants/a/TRADE.md',
      content: '自动沉淀内容',
      readOnly: true,
      version: 'doc-v1',
    })
  })
})
