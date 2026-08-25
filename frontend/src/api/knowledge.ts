import type { components } from '@/api/generated'

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

export async function createKnowledgeDocument(
  path: string,
  content: string,
  signal: AbortSignal,
): Promise<KnowledgeDocument> {
  const transport = await resolveTransport()
  const response = await transport(
    { path: '/api/admin/knowledge/documents', method: 'POST', body: { path, content }, auth: 'admin' },
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
    { path: '/api/admin/knowledge/business-domains', method: 'POST', body: { name }, auth: 'admin' },
    signal,
  )
  return toKnowledgeTreeNode(
    (await response.json()) as components['schemas']['KnowledgeTreeNode'],
  )
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
  return toKnowledgeTreeNode(
    (await response.json()) as components['schemas']['KnowledgeTreeNode'],
  )
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
