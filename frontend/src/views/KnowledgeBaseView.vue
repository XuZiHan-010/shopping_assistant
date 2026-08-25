<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import AdminTokenDialog from '@/components/knowledge/AdminTokenDialog.vue'
import ConfirmDeleteDialog from '@/components/knowledge/ConfirmDeleteDialog.vue'
import DocumentEditor from '@/components/knowledge/DocumentEditor.vue'
import KnowledgeTree from '@/components/knowledge/KnowledgeTree.vue'
import PromptDialog from '@/components/knowledge/PromptDialog.vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { canDeleteNode, isBusinessDomain, isDocumentParent } from '@/utils/knowledgeTree'

type DialogType = 'create-document' | 'create-domain' | 'rename-domain' | 'delete' | null

const knowledgeStore = useKnowledgeStore()
const authorizationError = ref('')
const dialog = ref<DialogType>(null)
const dialogError = ref('')
const dialogPending = ref(false)

const selectedNode = computed(() => knowledgeStore.selectedNode)
const canCreateDocument = computed(() => isDocumentParent(selectedNode.value))
const canRenameDomain = computed(() => isBusinessDomain(selectedNode.value))
const canDelete = computed(() => canDeleteNode(selectedNode.value))

async function authorize(token: string): Promise<void> {
  authorizationError.value = ''
  knowledgeStore.setAdminToken(token)
  try {
    await knowledgeStore.loadTree()
  } catch (error) {
    authorizationError.value = error instanceof Error ? error.message : '管理员令牌验证失败。'
    knowledgeStore.signOut()
  }
}

async function selectPath(path: string): Promise<void> {
  await knowledgeStore.selectNode(path)
}

function openDialog(type: DialogType): void {
  dialogError.value = ''
  dialog.value = type
}

function closeDialog(): void {
  dialog.value = null
  dialogError.value = ''
  dialogPending.value = false
}

function createDocumentPath(name: string): string {
  const filename = name.toLowerCase().endsWith('.md') ? name : `${name}.md`
  const parent = selectedNode.value?.path ?? 'index'
  return `${parent}/${filename}`
}

async function submitDialog(value: string): Promise<void> {
  dialogPending.value = true
  dialogError.value = ''
  try {
    if (dialog.value === 'create-document') {
      await knowledgeStore.createDocument(createDocumentPath(value), `# ${value}\n\n`)
    } else if (dialog.value === 'create-domain') {
      await knowledgeStore.createDomain(value)
    } else if (dialog.value === 'rename-domain') {
      await knowledgeStore.renameDomain(value)
    }
    closeDialog()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '操作失败，请重试。'
  } finally {
    dialogPending.value = false
  }
}

async function confirmDelete(): Promise<void> {
  dialogPending.value = true
  dialogError.value = ''
  try {
    await knowledgeStore.deleteSelected()
    closeDialog()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '删除失败，请重试。'
  } finally {
    dialogPending.value = false
  }
}

onMounted(() => {
  if (knowledgeStore.adminToken) {
    void knowledgeStore.loadTree().catch((error: unknown) => {
      authorizationError.value = error instanceof Error ? error.message : '管理员令牌验证失败。'
      knowledgeStore.signOut()
    })
  }
})
</script>

<template>
  <main class="knowledge-base">
    <template v-if="!knowledgeStore.adminToken">
      <AdminTokenDialog @submit="authorize" />
      <p v-if="authorizationError" class="knowledge-base__authorization-error" role="alert">
        {{ authorizationError }}
      </p>
    </template>
    <template v-else>
      <header class="knowledge-base__header">
        <div>
          <p>BOROUGH · KNOWLEDGE OPS</p>
          <h1>知识库维护后台</h1>
        </div>
        <button type="button" @click="knowledgeStore.signOut">退出后台</button>
      </header>
      <p v-if="knowledgeStore.errorMessage" role="alert">{{ knowledgeStore.errorMessage }}</p>
      <section class="knowledge-base__workspace">
        <KnowledgeTree
          :roots="knowledgeStore.roots"
          :selected-path="knowledgeStore.selectedPath"
          @select="selectPath"
          @create-domain="openDialog('create-domain')"
        />
        <div class="knowledge-base__content">
          <div class="knowledge-base__toolbar">
            <button
              type="button"
              data-testid="create-document"
              :disabled="!canCreateDocument"
              @click="openDialog('create-document')"
            >
              新建文档
            </button>
            <button
              type="button"
              data-testid="rename-domain"
              :disabled="!canRenameDomain"
              @click="openDialog('rename-domain')"
            >
              重命名业务域
            </button>
            <button
              type="button"
              data-testid="delete-node"
              :disabled="!canDelete"
              @click="openDialog('delete')"
            >
              删除
            </button>
          </div>
          <p v-if="knowledgeStore.loading">正在加载知识目录…</p>
          <DocumentEditor
            v-else-if="knowledgeStore.selectedDocument"
            :document="knowledgeStore.selectedDocument"
            :save="knowledgeStore.saveDocument"
          />
          <p v-else>请选择一篇文档进行维护。</p>
        </div>
      </section>
    </template>

    <PromptDialog
      v-if="dialog === 'create-document'"
      title="新建文档"
      label="文档名称"
      placeholder="例如：订单履约口径.md"
      :error-message="dialogError"
      :pending="dialogPending"
      @submit="submitDialog"
      @cancel="closeDialog"
    />
    <PromptDialog
      v-else-if="dialog === 'create-domain'"
      title="新建业务域"
      label="业务域名称"
      placeholder="例如：客服"
      :error-message="dialogError"
      :pending="dialogPending"
      @submit="submitDialog"
      @cancel="closeDialog"
    />
    <PromptDialog
      v-else-if="dialog === 'rename-domain'"
      title="重命名业务域"
      label="业务域名称"
      :initial-value="selectedNode?.name ?? ''"
      :error-message="dialogError"
      :pending="dialogPending"
      @submit="submitDialog"
      @cancel="closeDialog"
    />
    <ConfirmDeleteDialog
      v-else-if="dialog === 'delete' && selectedNode"
      :name="selectedNode.name"
      :path="selectedNode.path"
      :is-domain="isBusinessDomain(selectedNode)"
      :error-message="dialogError"
      :pending="dialogPending"
      @confirm="confirmDelete"
      @cancel="closeDialog"
    />
  </main>
</template>

<style scoped>
.knowledge-base {
  min-height: 100vh;
  padding: var(--space-6);
  background: var(--color-surface-muted);
}

.knowledge-base__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 76rem;
  margin: 0 auto var(--space-4);
}

.knowledge-base__header p {
  margin: 0;
  color: var(--color-teal);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-title);
  letter-spacing: 0.12em;
}

.knowledge-base__header h1 {
  margin: var(--space-1) 0 0;
}

.knowledge-base__header button {
  min-height: var(--control-height);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: white;
}

.knowledge-base__workspace {
  display: grid;
  grid-template-columns: minmax(15rem, 0.28fr) 1fr;
  min-height: 32rem;
  max-width: 76rem;
  margin: 0 auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-column);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.knowledge-base__content {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.knowledge-base__toolbar {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.knowledge-base__toolbar button {
  min-height: 2rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
  padding: 0 var(--space-3);
  color: var(--color-text-secondary);
  background: white;
  font-size: var(--font-size-caption);
}

.knowledge-base__toolbar button:disabled {
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.knowledge-base__content > p {
  padding: var(--space-5);
  color: var(--color-text-secondary);
}

.knowledge-base__authorization-error {
  width: min(100%, 31rem);
  margin: calc(-1 * var(--space-6)) auto 0;
  color: var(--color-danger-text);
}
</style>
