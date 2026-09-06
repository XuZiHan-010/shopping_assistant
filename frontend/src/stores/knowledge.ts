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

  /**
   * 每次语言切换递增一次。写状态之前先比较请求发出时快照的 epoch 与当前
   * epoch——不一致说明这个响应对应的是已经被切走的语言，直接丢弃，不写入
   * Store（与 `stores/chat.ts` 同一套机制，Task 11 Step 6 的原子刷新/防
   * 竞态防护——之前只在 chat.ts 落地，本次补齐到 knowledge.ts）。
   *
   * 这里的风险比另外两个 Store 更高：`selectedDocument` 一旦被过期响应
   * 覆盖成错误语言的内容，管理员如果没注意到就直接保存（默认
   * `isSourceVersion: true`），会把源文档本身覆盖成错误语言——不只是一次
   * UI 展示错误，是一次真实的数据损坏。
   */
  const localeEpoch = ref(0)

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
    const epochAtRequest = localeEpoch.value
    const document = await getKnowledgeDocument(path, new AbortController().signal, {
      contentLocale: localeStore.locale,
    })
    // 响应回来之前又发生了一次语言切换：这份文档对应的是已经过期的语言，
    // 丢弃，交给更晚那次 reloadForLocale/selectNode 的请求收尾——不能让它
    // 覆盖已经写入的正确语言内容（见上面 localeEpoch 的风险说明）。
    if (epochAtRequest !== localeEpoch.value) return
    selectedDocument.value = document
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
    // 无条件先递增：即使这次调用本身是 no-op（未登录/未选中文档），也要让
    // 任何仍在途的旧 epoch 请求（例如手动点开这份文档触发的 loadDocument()）
    // 在响应回来时被判定为过期而丢弃。
    localeEpoch.value += 1
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
