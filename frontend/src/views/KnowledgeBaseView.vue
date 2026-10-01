<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import ConfirmDeleteDialog from '@/components/knowledge/ConfirmDeleteDialog.vue'
import DocumentEditor from '@/components/knowledge/DocumentEditor.vue'
import KnowledgeTree from '@/components/knowledge/KnowledgeTree.vue'
import LanguageSwitcher from '@/components/layout/LanguageSwitcher.vue'
import PromptDialog from '@/components/knowledge/PromptDialog.vue'
import AdminGate from '@/components/shell/AdminGate.vue'
import { useKnowledgeStore } from '@/stores/knowledge'
import { canDeleteNode, isBusinessDomain, isDocumentParent } from '@/utils/knowledgeTree'

type DialogType = 'create-document' | 'create-domain' | 'rename-domain' | 'delete' | null

const { t } = useI18n()
const knowledgeStore = useKnowledgeStore()
const dialog = ref<DialogType>(null)
const dialogError = ref('')
const dialogPending = ref(false)

const selectedNode = computed(() => knowledgeStore.selectedNode)
const canCreateDocument = computed(() => isDocumentParent(selectedNode.value))
const canRenameDomain = computed(() => isBusinessDomain(selectedNode.value))
const canDelete = computed(() => canDeleteNode(selectedNode.value))

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
    dialogError.value = error instanceof Error ? error.message : t('knowledgeBaseView.actionFailed')
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
    dialogError.value = error instanceof Error ? error.message : t('knowledgeBaseView.deleteFailed')
  } finally {
    dialogPending.value = false
  }
}
</script>

<template>
  <!-- 外壳已经提供 <main id="main">；本页只用普通容器，不再嵌套第二个 main 地标。 -->
  <div class="kb">
    <!-- 全页唯一的语言切换器：放在令牌闸门之外，授权前后都能切换（AdminGate 不再自带一个）。 -->
    <div class="kb__locale">
      <LanguageSwitcher />
    </div>
    <AdminGate>
      <header class="kb__head">
        <div class="kb__intro">
          <p class="kb__eyebrow">{{ t('knowledgeBaseView.eyebrow') }}</p>
          <h1>{{ t('knowledgeBaseView.title') }}</h1>
          <p class="kb__sub">{{ t('knowledgeBaseView.sub') }}</p>
        </div>
        <button class="kb__sign-out" type="button" @click="knowledgeStore.signOut">
          {{ t('knowledgeBaseView.signOut') }}
        </button>
      </header>
      <p v-if="knowledgeStore.errorMessage" class="kb__error" role="alert">
        {{ knowledgeStore.errorMessage }}
      </p>
      <section class="kb__workspace">
        <KnowledgeTree
          :roots="knowledgeStore.roots"
          :selected-path="knowledgeStore.selectedPath"
          :read-only-access="knowledgeStore.isReadOnlyToken"
          @select="selectPath"
          @create-domain="openDialog('create-domain')"
        />
        <div class="kb__content">
          <p
            v-if="knowledgeStore.isReadOnlyToken"
            class="kb__readonly"
            data-testid="readonly-notice"
            role="status"
          >
            {{ t('knowledgeBaseView.readOnlyNotice') }}
          </p>
          <div v-else class="kb__toolbar">
            <button
              type="button"
              data-testid="create-document"
              :disabled="!canCreateDocument"
              @click="openDialog('create-document')"
            >
              {{ t('knowledgeBaseView.newDocument') }}
            </button>
            <button
              type="button"
              data-testid="rename-domain"
              :disabled="!canRenameDomain"
              @click="openDialog('rename-domain')"
            >
              {{ t('knowledgeBaseView.renameDomain') }}
            </button>
            <button
              type="button"
              class="kb__danger"
              data-testid="delete-node"
              :disabled="!canDelete"
              @click="openDialog('delete')"
            >
              {{ t('knowledgeBaseView.deleteNode') }}
            </button>
          </div>
          <p v-if="knowledgeStore.loading" class="kb__placeholder">
            {{ t('knowledgeBaseView.loadingTree') }}
          </p>
          <DocumentEditor
            v-else-if="knowledgeStore.selectedDocument"
            :document="knowledgeStore.selectedDocument"
            :read-only-access="knowledgeStore.isReadOnlyToken"
            :save="knowledgeStore.saveDocument"
          />
          <p v-else class="kb__placeholder">{{ t('knowledgeBaseView.selectDocumentPrompt') }}</p>
        </div>
      </section>
    </AdminGate>

    <PromptDialog
      v-if="dialog === 'create-document'"
      :title="t('knowledgeBaseView.createDocumentTitle')"
      :label="t('knowledgeBaseView.createDocumentLabel')"
      :placeholder="t('knowledgeBaseView.createDocumentPlaceholder')"
      :error-message="dialogError"
      :pending="dialogPending"
      @submit="submitDialog"
      @cancel="closeDialog"
    />
    <PromptDialog
      v-else-if="dialog === 'create-domain'"
      :title="t('knowledgeBaseView.createDomainTitle')"
      :label="t('knowledgeBaseView.createDomainLabel')"
      :placeholder="t('knowledgeBaseView.createDomainPlaceholder')"
      :error-message="dialogError"
      :pending="dialogPending"
      @submit="submitDialog"
      @cancel="closeDialog"
    />
    <PromptDialog
      v-else-if="dialog === 'rename-domain'"
      :title="t('knowledgeBaseView.renameDomainTitle')"
      :label="t('knowledgeBaseView.renameDomainLabel')"
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
  </div>
</template>

<style scoped>
/*
 * 知识库（「管理」分组，须管理员令牌）：铸铁绿页眉条 + 目录树 | 编辑器两栏，
 * 与「运营」分组里卡片式的商家记忆页明确区分（PRD M11）。
 */
.kb {
  max-width: 1160px;
  margin: 0 auto;
  padding: 30px 36px 56px;
}

.kb__locale {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.kb__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px 20px;
  margin-bottom: 16px;
  padding: 18px 22px;
  border-radius: var(--radius);
  background: var(--side-bg);
  color: var(--side-ink);
}

.kb__intro {
  min-width: 0;
}

.kb__eyebrow {
  margin: 0 0 4px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: var(--gilt);
}

.kb__head h1 {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(24px, 2.4vw, 30px);
  font-weight: 600;
  letter-spacing: -0.015em;
  line-height: 1.15;
}

.kb__sub {
  max-width: 64ch;
  margin: 6px 0 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--side-2);
}

.kb__sign-out {
  flex-shrink: 0;
  height: 32px;
  padding: 0 12px;
  border: 1px solid var(--side-line);
  border-radius: 8px;
  background: var(--side-hover);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--side-ink);
}

.kb__sign-out:hover {
  background: var(--side-active);
}

.kb__error {
  margin: 0 0 12px;
  padding: 9px 14px;
  border-radius: 10px;
  background: var(--danger-soft);
  font-size: 13px;
  color: var(--danger);
}

.kb__workspace {
  display: grid;
  grid-template-columns: minmax(14rem, 0.28fr) minmax(0, 1fr);
  min-height: 32rem;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--card);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.kb__content {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.kb__toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
}

.kb__toolbar button {
  height: 30px;
  padding: 0 11px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  background: var(--raised);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink);
}

.kb__toolbar button:hover:not(:disabled) {
  background: var(--hover);
}

.kb__toolbar .kb__danger:not(:disabled) {
  color: var(--danger);
}

.kb__toolbar button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.kb__readonly {
  margin: 0;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--gilt-soft);
  font-size: 12.5px;
  color: var(--gilt-ink);
}

.kb__placeholder {
  margin: 0;
  padding: 22px 18px;
  font-size: 13px;
  color: var(--ink-soft);
}

@media (max-width: 820px) {
  .kb {
    padding: 18px 16px 40px;
  }

  .kb__head {
    flex-direction: column;
    align-items: flex-start;
    padding: 16px;
  }

  .kb__workspace {
    grid-template-columns: minmax(0, 1fr);
    min-height: 0;
  }
}
</style>
