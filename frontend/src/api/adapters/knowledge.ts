import type { components } from '@/api/generated'

type RawKnowledgeTreeNode = components['schemas']['KnowledgeTreeNode']

/**
 * 字面量取值逐字对应后端 `ContentLanguage` / `TranslationStatus`
 * （`backend/app/schemas/knowledge.py`），并与 `generated.ts` 里
 * `KnowledgeDocumentResponse.content_locale` / `.translation_status` 的
 * 枚举保持索引派生，不重复手写取值列表。
 */
export type ContentLanguage = components['schemas']['KnowledgeDocumentResponse']['content_locale']
export type TranslationStatus =
  components['schemas']['KnowledgeDocumentResponse']['translation_status']

type RawKnowledgeDocument = components['schemas']['KnowledgeDocumentResponse']
type RawKnowledgeIndexStatus = components['schemas']['KnowledgeIndexStatus']

/** 知识索引状态（契约 §8.6.7）；取值从 `generated.ts` 派生，不重复手写。 */
export interface KnowledgeIndexStatus {
  retrievalMode: RawKnowledgeIndexStatus['retrieval_mode']
  activeVersion: number | null
  embeddingModel: string | null
  configuredModel: string | null
  stale: boolean
  staleReason: RawKnowledgeIndexStatus['stale_reason']
  building: boolean
  lastFailureReason: RawKnowledgeIndexStatus['last_failure_reason']
}

export interface KnowledgeTreeSnapshot {
  roots: KnowledgeTreeNode[]
  indexStatus: KnowledgeIndexStatus
}

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
  /**
   * `content` 实际使用的语言：源语言本身，或命中的人工译文目标语言。
   * 可选是因为测试和早期调用点可能直接构造字面量——消费方一律按缺省值兜底
   * （`toKnowledgeDocument` 同一套兜底）。
   */
  contentLocale?: ContentLanguage
  /** `content` 相对请求方指定 `content_locale`（若提供）所处的状态。 */
  translationStatus?: TranslationStatus
}

export function toKnowledgeTree(
  response: components['schemas']['KnowledgeTreeResponse'],
): KnowledgeTreeNode[] {
  return response.roots.map(toKnowledgeTreeNode)
}

export function toKnowledgeIndexStatus(raw: RawKnowledgeIndexStatus): KnowledgeIndexStatus {
  return {
    retrievalMode: raw.retrieval_mode,
    activeVersion: raw.active_version ?? null,
    embeddingModel: raw.embedding_model ?? null,
    configuredModel: raw.configured_model ?? null,
    stale: raw.stale,
    staleReason: raw.stale_reason ?? null,
    building: raw.building,
    lastFailureReason: raw.last_failure_reason ?? null,
  }
}

export function toKnowledgeTreeSnapshot(
  response: components['schemas']['KnowledgeTreeResponse'],
): KnowledgeTreeSnapshot {
  return {
    roots: toKnowledgeTree(response),
    indexStatus: toKnowledgeIndexStatus(response.index_status),
  }
}

export function toKnowledgeDocument(raw: RawKnowledgeDocument): KnowledgeDocument {
  return {
    path: raw.path,
    content: raw.content,
    readOnly: raw.read_only,
    version: raw.version,
    // 字段本身已是必填，`?? 'und'` 只兜手写测试字面量省略该字段的情况，与
    // 请求方未指定 content_locale 时的后端缺省行为一致：原样当作源正文处理。
    contentLocale: raw.content_locale ?? 'und',
    translationStatus: raw.translation_status ?? 'SOURCE',
  }
}

export function toKnowledgeTreeNode(raw: RawKnowledgeTreeNode): KnowledgeTreeNode {
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
