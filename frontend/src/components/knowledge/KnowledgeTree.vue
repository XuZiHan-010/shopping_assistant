<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { useLocaleStore } from '@/stores/locale'
import { displayNodeName } from '@/utils/knowledgeTree'

const props = withDefaults(defineProps<{ roots: KnowledgeTreeNode[]; selectedPath?: string }>(), {
  selectedPath: '',
})
const emit = defineEmits<{ select: [path: string]; 'create-domain': [] }>()

const { t } = useI18n()
const localeStore = useLocaleStore()

interface FlattenedNode {
  node: KnowledgeTreeNode
  depth: number
}

const nodes = computed<FlattenedNode[]>(() => {
  const flattened: FlattenedNode[] = []
  const visit = (node: KnowledgeTreeNode, depth: number): void => {
    flattened.push({ node, depth })
    node.children.forEach((child) => visit(child, depth + 1))
  }
  props.roots.forEach((root) => visit(root, 0))
  return flattened
})
</script>

<template>
  <nav class="knowledge-tree" :aria-label="t('knowledgeTree.navAria')">
    <div class="knowledge-tree__header">
      <p class="knowledge-tree__title">{{ t('knowledgeTree.title') }}</p>
      <button
        type="button"
        data-testid="create-domain"
        :title="t('knowledgeTree.createDomainAria')"
        :aria-label="t('knowledgeTree.createDomainAria')"
        @click="emit('create-domain')"
      >
        {{ t('knowledgeTree.createDomainLabel') }}
      </button>
    </div>
    <ul>
      <li v-for="item in nodes" :key="item.node.path">
        <button
          type="button"
          :data-path="item.node.path"
          :aria-current="item.node.path === selectedPath ? 'true' : undefined"
          :class="{ 'knowledge-tree__item--selected': item.node.path === selectedPath }"
          :style="{ paddingLeft: `${8 + item.depth * 14}px` }"
          @click="emit('select', item.node.path)"
        >
          <span>{{ item.node.nodeType === 'directory' ? '▣' : '▤' }}</span
          >{{ displayNodeName(item.node, localeStore.locale) }}
          <small v-if="item.node.readOnly">{{ t('knowledgeTree.readOnlyBadge') }}</small>
        </button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.knowledge-tree {
  min-width: 15rem;
  padding: var(--space-4);
  border-right: 1px solid var(--color-border);
}
.knowledge-tree__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.knowledge-tree__title {
  margin: 0;
  font-weight: var(--font-weight-title);
}

.knowledge-tree__header button {
  min-height: 1.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-small);
  padding: 0 var(--space-2);
  color: var(--color-text-secondary);
  background: white;
  font-size: var(--font-size-caption);
}

.knowledge-tree__item--selected {
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
}
ul {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
button {
  width: 100%;
  display: flex;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-2);
  border: 0;
  border-radius: var(--radius-small);
  color: var(--color-text-secondary);
  background: transparent;
  text-align: left;
}
button:hover {
  color: var(--color-primary-strong);
  background: var(--color-primary-soft);
}
small {
  margin-left: auto;
  color: var(--color-text-muted);
}
</style>
