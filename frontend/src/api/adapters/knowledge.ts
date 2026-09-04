import type { components } from '@/api/generated'

type RawKnowledgeTreeNode = components['schemas']['KnowledgeTreeNode']

/**
 * `generated.ts` 还没有 `content_locale`/`translation_status`（Task 8 新增，
 * 本文件写作时 `generated.ts` 尚未重新生成——见 `docs/backend-development-plan.md`
 * 与 `backend/app/schemas/knowledge.py::KnowledgeDocumentResponse`）。
 * Task 12 重新生成后，这两个字段会并入 `generated.ts` 的
 * `KnowledgeDocumentResponse`，届时这里的手工补丁类型可以直接删掉，改回
 * `components['schemas']['KnowledgeDocumentResponse']`。
 *
 * 字面量取值逐字对应后端 `ContentLanguage` / `TranslationStatus`
 * （`backend/app/schemas/knowledge.py`）。
 */
export type ContentLanguage = 'zh-CN' | 'en-US' | 'mixed' | 'und'
export type TranslationStatus = 'SOURCE' | 'CURRENT' | 'STALE' | 'MISSING'

type RawKnowledgeDocument = components['schemas']['KnowledgeDocumentResponse'] & {
  content_locale?: ContentLanguage
  translation_status?: TranslationStatus
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
   * 可选是因为测试和早期调用点可能直接构造字面量，不带这两个 Task 8/11
   * 新字段——消费方一律按缺省值兜底（`toKnowledgeDocument` 同一套兜底）。
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

export function toKnowledgeDocument(raw: RawKnowledgeDocument): KnowledgeDocument {
  return {
    path: raw.path,
    content: raw.content,
    readOnly: raw.read_only,
    version: raw.version,
    // 手工补丁字段暂缺时（Mock 尚未跟进、或旧响应）退回 SOURCE/请求方未指定
    // content_locale 时的后端缺省行为一致：原样当作源正文处理。
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
