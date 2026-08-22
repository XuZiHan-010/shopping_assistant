<script setup lang="ts">
import { onMounted, ref } from 'vue'

import AdminTokenDialog from '@/components/knowledge/AdminTokenDialog.vue'
import DocumentEditor from '@/components/knowledge/DocumentEditor.vue'
import KnowledgeTree from '@/components/knowledge/KnowledgeTree.vue'
import { useKnowledgeStore } from '@/stores/knowledge'

const knowledgeStore = useKnowledgeStore()
const authorizationError = ref('')

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
  if (!path.toLowerCase().endsWith('.md')) return
  await knowledgeStore.loadDocument(path)
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
        <KnowledgeTree :roots="knowledgeStore.roots" @select="selectPath" />
        <p v-if="knowledgeStore.loading">正在加载知识目录…</p>
        <DocumentEditor
          v-else-if="knowledgeStore.selectedDocument"
          :document="knowledgeStore.selectedDocument"
          :save="knowledgeStore.saveDocument"
        />
        <p v-else>请选择一篇文档进行维护。</p>
      </section>
    </template>
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

.knowledge-base__workspace > p {
  padding: var(--space-5);
  color: var(--color-text-secondary);
}

.knowledge-base__authorization-error {
  width: min(100%, 31rem);
  margin: calc(-1 * var(--space-6)) auto 0;
  color: var(--color-danger-text);
}
</style>
