import { ref } from 'vue'
import { defineStore } from 'pinia'

import { getKnowledgeDocument, getKnowledgeTree, updateKnowledgeDocument } from '@/api/knowledge'
import type { KnowledgeDocument, KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { AppError } from '@/api/errors'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const adminToken = ref('')
  const roots = ref<KnowledgeTreeNode[]>([])
  const selectedDocument = ref<KnowledgeDocument | undefined>(undefined)
  const loading = ref(false)
  const errorMessage = ref('')

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
    errorMessage.value = ''
  }

  return {
    adminToken,
    roots,
    selectedDocument,
    loading,
    errorMessage,
    setAdminToken,
    adminHeaders,
    loadTree,
    loadDocument,
    saveDocument,
    signOut,
  }
})
