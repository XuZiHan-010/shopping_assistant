import type { components } from '@/api/generated'

import {
  toKnowledgeDocument,
  toKnowledgeTree,
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

export async function getKnowledgeDocument(
  path: string,
  signal: AbortSignal,
): Promise<KnowledgeDocument> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/knowledge/documents/${encodeDocumentPath(path)}`,
      method: 'GET',
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeDocument(
    (await response.json()) as components['schemas']['KnowledgeDocumentResponse'],
  )
}

export async function updateKnowledgeDocument(
  path: string,
  content: string,
  ifMatch: string,
  signal: AbortSignal,
): Promise<KnowledgeDocument> {
  const transport = await resolveTransport()
  const response = await transport(
    {
      path: `/api/admin/knowledge/documents/${encodeDocumentPath(path)}`,
      method: 'PUT',
      body: { content },
      headers: { 'If-Match': ifMatch },
      auth: 'admin',
    },
    signal,
  )
  return toKnowledgeDocument(
    (await response.json()) as components['schemas']['KnowledgeDocumentResponse'],
  )
}
