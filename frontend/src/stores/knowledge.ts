import { computed, ref, watch } from 'vue'
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
  type UpdateKnowledgeDocumentOptions,
} from '@/api/knowledge'
import type { KnowledgeDocument, KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { AppError } from '@/api/errors'
import { findNode, isBusinessDomain } from '@/utils/knowledgeTree'

import { useLocaleStore } from './locale'

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

  const localeStore = useLocaleStore()

  /**
   * 按当前展示语言请求文档——`content_locale` 与后端约定：等于源语言（或
   * 后端判定源本身就是这个语言）时原样返回源正文（`translation_status`
   * 为 `SOURCE`），否则按人工译文的实际状态返回 `CURRENT`/`STALE`/`MISSING`
   * （Task 8）。管理后台默认按"你现在正在看哪个语言的界面"决定要看哪个
   * 语言的知识库内容，语言切换时会重新拉一次（见下方 `reloadForLocale`）。
   */
  async function loadDocument(path: string): Promise<void> {
    if (!adminToken.value) throw new AppError('AUTH_REQUIRED', '未授权，请先输入管理员令牌。')
    selectedDocument.value = await getKnowledgeDocument(path, new AbortController().signal, {
      contentLocale: localeStore.locale,
    })
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

  /**
   * `options` 由调用方（`DocumentEditor.vue`）显式传入 `isSourceVersion`/
   * `contentLocale`，本函数不做任何"比较两个 locale 猜意图"的推断——那正是
   * Task 11 要收掉的坑（见 `DocumentEditor.vue` 的说明）。缺省
   * （`options` 为空）等价于更新源版本，与这个参数引入前的行为完全一致。
   */
  async function saveDocument(
    content: string,
    headers: Record<string, string>,
    options: UpdateKnowledgeDocumentOptions = {},
  ): Promise<void> {
    const document = selectedDocument.value
    if (!document) return
    selectedDocument.value = await updateKnowledgeDocument(
      document.path,
      content,
      headers['If-Match'] ?? '',
      new AbortController().signal,
      options,
    )
  }

  function signOut(): void {
    adminToken.value = ''
    roots.value = []
    selectedDocument.value = undefined
    selectedPath.value = ''
    errorMessage.value = ''
  }

  /**
   * 语言切换时，若当前正选中一份文档，按新语言重新拉一次——切到英文应该
   * 看到英文译文（或"尚无译文"的 MISSING 状态），不是继续停在上一语言的
   * 正文。目录树本身不重拉：节点名称/路径不随展示语言变化。未登录、未选中
   * 文档、或选中的是目录（非 `.md`）时都直接跳过。
   */
  async function reloadForLocale(): Promise<void> {
    if (!adminToken.value) return
    if (!selectedPath.value.toLowerCase().endsWith('.md')) return
    try {
      await loadDocument(selectedPath.value)
    } catch {
      // 静默失败：保留当前已展示的文档内容，不能让一次语言切换的刷新失败
      // 打断管理员正在编辑的东西。
    }
  }

  watch(
    () => localeStore.locale,
    () => {
      void reloadForLocale()
    },
  )

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
    reloadForLocale,
  }
})
