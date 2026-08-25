<script setup lang="ts">
import { computed } from 'vue'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'

const props = withDefaults(defineProps<{ roots: KnowledgeTreeNode[]; selectedPath?: string }>(), {
  selectedPath: '',
})
const emit = defineEmits<{ select: [path: string]; 'create-domain': [] }>()

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
  <nav class="knowledge-tree" aria-label="知识库目录">
    <div class="knowledge-tree__header">
      <p class="knowledge-tree__title">知识目录</p>
      <button
        type="button"
        data-testid="create-domain"
        title="新建业务域"
        aria-label="新建业务域"
        @click="emit('create-domain')"
      >
        + 业务域
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
          >{{ item.node.name }}
          <small v-if="item.node.readOnly">只读</small>
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
