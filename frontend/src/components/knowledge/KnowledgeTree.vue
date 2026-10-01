<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { useLocaleStore } from '@/stores/locale'
import { displayNodeName } from '@/utils/knowledgeTree'

const props = withDefaults(
  defineProps<{ roots: KnowledgeTreeNode[]; selectedPath?: string; readOnlyAccess?: boolean }>(),
  { selectedPath: '', readOnlyAccess: false },
)
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
        v-if="!props.readOnlyAccess"
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
  min-width: 0;
  padding: 12px 10px;
  border-right: 1px solid var(--line);
  background: var(--chrome);
}
.knowledge-tree__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  padding: 0 6px;
}

.knowledge-tree__title {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ink-soft);
}

.knowledge-tree__header button {
  width: auto;
  min-height: 1.75rem;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-small);
  padding: 0 var(--space-2);
  color: var(--ink-2);
  background: var(--raised);
  font-size: var(--font-size-caption);
  font-weight: 600;
}

.knowledge-tree__header button:hover {
  color: var(--ink);
  background: var(--hover);
}

ul {
  display: grid;
  gap: 1px;
  margin: 0;
  padding: 0;
  list-style: none;
}
button {
  width: 100%;
  display: flex;
  gap: var(--space-2);
  align-items: center;
  min-width: 0;
  padding: 6px 9px;
  border: 0;
  border-radius: 7px;
  color: var(--ink-2);
  background: transparent;
  font-size: 13.5px;
  text-align: left;
  overflow-wrap: anywhere;
}
button > span {
  flex-shrink: 0;
  color: var(--ink-faint);
}
button:hover {
  color: var(--ink);
  background: var(--hover);
}
.knowledge-tree__item--selected,
.knowledge-tree__item--selected:hover {
  color: var(--ink);
  background: var(--well);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--accent);
}
small {
  flex-shrink: 0;
  margin-left: auto;
  padding: 0 6px;
  border-radius: 99px;
  background: var(--gilt-soft);
  color: var(--gilt-ink);
  font-size: 11px;
  font-weight: 600;
}
@media (max-width: 820px) {
  .knowledge-tree {
    border-right: 0;
    border-bottom: 1px solid var(--line);
    max-height: 18rem;
    overflow-y: auto;
  }
}
</style>
