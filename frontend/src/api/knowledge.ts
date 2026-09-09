import type { components } from '@/api/generated'
import type { SupportedLocale } from '@/i18n'

import {
  toKnowledgeDocument,
  toKnowledgeTree,
  toKnowledgeTreeNode,
  type KnowledgeDocument,
  type KnowledgeTreeNode,
} from './adapters/knowledge'
import { resolveTransport } from './transport'

export async function getKnowledgeTree(signal: AbortSignal): Promise<KnowledgeTreeNode[]> {
  const transport = await resolveTransport()
  const response = await transport(
    { path: '/api/admin/knowledge/tree', method: 'GET', auth: 'admin' },
    signal,
  )
  const payload = (await response.json()) as components['schemas']['KnowledgeTreeResponse']
  return toKnowledgeTree(payload)
}

function encodeDocumentPath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/')
}

export interface GetKnowledgeDocumentOptions {
  /**
   * 缺省时行为与本字段引入前完全一致：原样返回源正文，不涉及任何人工译文
   * 查找（后端 `KnowledgeAdminService.get_document`，Task 8 向后兼容）。
   */
  contentLocale?: SupportedLocale
}

export async function getKnowledgeDocument(
  path: string,
  signal: AbortSignal,
  options: GetKnowledgeDocumentOptions = {},
): Promise<KnowledgeDocument> {
  const transport = await resolveTransport()
  const query = options.contentLocale
    ? `?${new URLSearchParams({ content_locale: options.contentLocale }).toString()}`
    : ''
  const response = await transport(
    {
      path: `/api/admin/knowledge/documents/${encodeDocumentPath(path)}${query}`,
      method: 'GET',
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeDocument(
    (await response.json()) as components['schemas']['KnowledgeDocumentResponse'],
  )
}

export interface UpdateKnowledgeDocumentOptions {
  /**
   * `true`（缺省）更新源标题/正文本身；`false` 改为保存一份人工译文，此时
   * 必须提供 `contentLocale`——不能靠"和源语言不一样的那个"去猜目标语言，
   * 源语言本身可以是 `mixed`/`und`（`backend/app/schemas/knowledge.py`
   * `KnowledgeDocumentUpdateRequest` 的文档字符串）。
   */
  isSourceVersion?: boolean
  contentLocale?: SupportedLocale
}

export async function updateKnowledgeDocument(
  path: string,
  content: string,
  ifMatch: string,
  signal: AbortSignal,
  options: UpdateKnowledgeDocumentOptions = {},
): Promise<KnowledgeDocument> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/knowledge/documents/${encodeDocumentPath(path)}`,
      method: 'PUT',
      body: {
        content,
        is_source_version: options.isSourceVersion ?? true,
        content_locale: options.contentLocale ?? null,
      },
      headers: { 'If-Match': ifMatch },
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeDocument(
    (await response.json()) as components['schemas']['KnowledgeDocumentResponse'],
  )
}

export async function createKnowledgeDocument(
  path: string,
  content: string,
  signal: AbortSignal,
): Promise<KnowledgeDocument> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: '/api/admin/knowledge/documents',
      method: 'POST',
      body: { path, content },
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeDocument(
    (await response.json()) as components['schemas']['KnowledgeDocumentResponse'],
  )
}

export async function deleteKnowledgeDocument(
  path: string,
  ifMatch: string,
  signal: AbortSignal,
): Promise<void> {
  const transport = await resolveTransport()
  await transport(
    {
      path: `/api/admin/knowledge/documents/${encodeDocumentPath(path)}`,
      method: 'DELETE',
      headers: { 'If-Match': ifMatch },
      auth: 'admin',
    },
    signal,
  )
}

export async function createBusinessDomain(
  name: string,
  signal: AbortSignal,
): Promise<KnowledgeTreeNode> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: '/api/admin/knowledge/business-domains',
      method: 'POST',
      body: { name },
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeTreeNode((await response.json()) as components['schemas']['KnowledgeTreeNode'])
}

export async function renameBusinessDomain(
  currentName: string,
  newName: string,
  ifMatch: string,
  signal: AbortSignal,
): Promise<KnowledgeTreeNode> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/knowledge/business-domains?name=${encodeURIComponent(currentName)}`,
      method: 'PUT',
      body: { new_name: newName },
      headers: { 'If-Match': ifMatch },
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeTreeNode((await response.json()) as components['schemas']['KnowledgeTreeNode'])
}

export async function deleteBusinessDomain(
  name: string,
  ifMatch: string,
  signal: AbortSignal,
): Promise<void> {
  const transport = await resolveTransport()
  await transport(
    {
      path: `/api/admin/knowledge/business-domains?name=${encodeURIComponent(name)}&recursive=true`,
      method: 'DELETE',
      headers: { 'If-Match': ifMatch },
      auth: 'admin',
    },
    signal,
  )
}
