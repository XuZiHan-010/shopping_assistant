<script setup lang="ts">
import { computed } from 'vue'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'

const props = defineProps<{ roots: KnowledgeTreeNode[] }>()
const emit = defineEmits<{ select: [path: string] }>()

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
    <p class="knowledge-tree__title">知识目录</p>
    <ul>
      <li v-for="item in nodes" :key="item.node.path">
        <button
          type="button"
          :data-path="item.node.path"
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
.knowledge-tree__title {
  margin: 0 0 var(--space-3);
  font-weight: var(--font-weight-title);
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
