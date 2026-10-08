import { describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'

import { toKnowledgeDocument, toKnowledgeTree, toKnowledgeTreeSnapshot } from './knowledge'

const INDEX_STATUS: components['schemas']['KnowledgeIndexStatus'] = {
  retrieval_mode: 'HYBRID',
  active_version: 1,
  embedding_model: 'm',
  configured_model: 'm',
  stale: false,
  stale_reason: null,
  building: false,
  last_failure_reason: null,
}

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
      index_status: INDEX_STATUS,
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
      index_status: INDEX_STATUS,
    } as components['schemas']['KnowledgeTreeResponse']

    expect(toKnowledgeTree(raw)[0]?.children).toEqual([])
  })

  it('完整映射文档并保留只读、版本、内容语言与译文状态', () => {
    const raw = {
      path: 'memory/merchants/a/TRADE.md',
      content: '自动沉淀内容',
      read_only: true,
      version: 'doc-v1',
      content_locale: 'zh-CN',
      translation_status: 'SOURCE',
    } as components['schemas']['KnowledgeDocumentResponse']

    expect(toKnowledgeDocument(raw)).toEqual({
      path: 'memory/merchants/a/TRADE.md',
      content: '自动沉淀内容',
      readOnly: true,
      version: 'doc-v1',
      contentLocale: 'zh-CN',
      translationStatus: 'SOURCE',
    })
  })

  it('命中人工译文时 content_locale/translation_status 如实反映（Task 8）', () => {
    const raw = {
      path: 'index/退货规则.md',
      content: 'Return policy content',
      read_only: false,
      version: 'doc-v2',
      content_locale: 'en-US',
      translation_status: 'CURRENT',
    } as components['schemas']['KnowledgeDocumentResponse']

    const document = toKnowledgeDocument(raw)

    expect(document.contentLocale).toBe('en-US')
    expect(document.translationStatus).toBe('CURRENT')
  })

  it('译文过期时 translation_status 为 STALE，content 已回退为源正文', () => {
    const raw = {
      path: 'index/退货规则.md',
      content: '退货规则（源正文，译文已过期回退）',
      read_only: false,
      version: 'doc-v3',
      content_locale: 'zh-CN',
      translation_status: 'STALE',
    } as components['schemas']['KnowledgeDocumentResponse']

    const document = toKnowledgeDocument(raw)

    expect(document.translationStatus).toBe('STALE')
    expect(document.content).toBe('退货规则（源正文，译文已过期回退）')
  })

  it('缺少 content_locale/translation_status 的旧响应退回 und/SOURCE', () => {
    const raw = {
      path: 'index/a.md',
      content: '正文',
      read_only: false,
      version: 'v1',
    } as components['schemas']['KnowledgeDocumentResponse']

    const document = toKnowledgeDocument(raw)

    expect(document.contentLocale).toBe('und')
    expect(document.translationStatus).toBe('SOURCE')
  })

  it('目录树响应同时映射索引状态（§8.6.7）', () => {
    const raw = {
      roots: [],
      index_status: {
        retrieval_mode: 'KEYWORD_ONLY',
        active_version: null,
        embedding_model: null,
        configured_model: 'bge',
        stale: true,
        stale_reason: 'CORPUS_CHANGED',
        building: true,
        last_failure_reason: 'EMBEDDING_FAILED',
      },
    } as components['schemas']['KnowledgeTreeResponse']

    expect(toKnowledgeTreeSnapshot(raw)).toEqual({
      roots: [],
      indexStatus: {
        retrievalMode: 'KEYWORD_ONLY',
        activeVersion: null,
        embeddingModel: null,
        configuredModel: 'bge',
        stale: true,
        staleReason: 'CORPUS_CHANGED',
        building: true,
        lastFailureReason: 'EMBEDDING_FAILED',
      },
    })
  })
})
