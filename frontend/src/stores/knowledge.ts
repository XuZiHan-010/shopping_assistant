import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createBusinessDomain as createBusinessDomainRequest,
  createKnowledgeDocument,
  deleteBusinessDomain as deleteBusinessDomainRequest,
  deleteKnowledgeDocument,
  getKnowledgeDocument,
  getKnowledgeTree,
  renameBusinessDomain as renameBusinessDomainRequest,
  updateKnowledgeDocument,
} from '@/api/knowledge'
import type { KnowledgeDocument, KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { AppError } from '@/api/errors'
import { findNode, isBusinessDomain } from '@/utils/knowledgeTree'

function quoteVersion(version: string): string {
  return `"${version}"`
}

export const useKnowledgeStore = defineStore('knowledge', () => {
  const adminToken = ref('')
  const roots = ref<KnowledgeTreeNode[]>([])
  const selectedDocument = ref<KnowledgeDocument | undefined>(undefined)
  const selectedPath = ref('')
  const loading = ref(false)
  const errorMessage = ref('')

  const selectedNode = computed(() => findNode(roots.value, selectedPath.value))

  function setAdminToken(token: string): void {
    adminToken.value = token.trim()
    errorMessage.value = ''
  }

  function adminHeaders(): Record<string, string> {
    return adminToken.value ? { 'X-Admin-Token': adminToken.value } : {}
  }

  async function loadTree(): Promise<void> {
    if (!adminToken.value) throw new AppError('AUTH_REQUIRED', '未授权，请先输入管理员令牌。')

    loading.value = true
    errorMessage.value = ''
    try {
      roots.value = await getKnowledgeTree(new AbortController().signal)
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '知识库目录加载失败。'
      throw error
    } finally {
      loading.value = false
    }
  }

  async function loadDocument(path: string): Promise<void> {
    if (!adminToken.value) throw new AppError('AUTH_REQUIRED', '未授权，请先输入管理员令牌。')
    selectedDocument.value = await getKnowledgeDocument(path, new AbortController().signal)
  }

  async function selectNode(path: string): Promise<void> {
    selectedPath.value = path
    if (path.toLowerCase().endsWith('.md')) {
      await loadDocument(path)
    } else {
      selectedDocument.value = undefined
    }
  }

  async function createDocument(path: string, content: string): Promise<void> {
    const created = await createKnowledgeDocument(path, content, new AbortController().signal)
    await loadTree()
    selectedPath.value = created.path
    selectedDocument.value = created
  }

  async function createDomain(name: string): Promise<void> {
    const domain = await createBusinessDomainRequest(name, new AbortController().signal)
    await loadTree()
    selectedPath.value = domain.path
    selectedDocument.value = undefined
  }

  async function renameDomain(newName: string): Promise<void> {
    const node = selectedNode.value
    if (!node) return
    const renamed = await renameBusinessDomainRequest(
      node.name,
      newName,
      quoteVersion(node.version),
      new AbortController().signal,
    )
    await loadTree()
    selectedPath.value = renamed.path
    selectedDocument.value = undefined
  }

  async function deleteSelected(): Promise<void> {
    const node = selectedNode.value
    if (!node) return
    if (isBusinessDomain(node)) {
      await deleteBusinessDomainRequest(
        node.name,
        quoteVersion(node.version),
        new AbortController().signal,
      )
    } else {
      const version =
        selectedDocument.value?.path === node.path ? selectedDocument.value.version : node.version
      await deleteKnowledgeDocument(node.path, quoteVersion(version), new AbortController().signal)
    }
    await loadTree()
    selectedPath.value = ''
    selectedDocument.value = undefined
  }

  async function saveDocument(content: string, headers: Record<string, string>): Promise<void> {
    const document = selectedDocument.value
    if (!document) return
    selectedDocument.value = await updateKnowledgeDocument(
      document.path,
      content,
      headers['If-Match'] ?? '',
      new AbortController().signal,
    )
  }

  function signOut(): void {
    adminToken.value = ''
    roots.value = []
    selectedDocument.value = undefined
    selectedPath.value = ''
    errorMessage.value = ''
  }

  return {
    adminToken,
    roots,
    selectedDocument,
    selectedPath,
    selectedNode,
    loading,
    errorMessage,
    setAdminToken,
    adminHeaders,
    loadTree,
    loadDocument,
    selectNode,
    createDocument,
    createDomain,
    renameDomain,
    deleteSelected,
    saveDocument,
    signOut,
  }
})
