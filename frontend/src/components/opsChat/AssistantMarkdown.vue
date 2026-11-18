<script setup lang="ts">
/**
 * 助手回答的受控 Markdown 渲染：结构来自 `utils/assistantMarkdown.ts`，这里只用模板文本插值
 * 输出，不使用 `v-html`。回答里出现的任何 HTML 都只会作为文字显示。
 *
 * 表格包在可横向滚动的容器里：助手栏很窄，宽表格在容器内滚动，不撑出页面横向滚动。
 */
import { computed, createTextVNode, h, type FunctionalComponent } from 'vue'

import { parseAssistantMarkdown, type InlineSegment } from '@/utils/assistantMarkdown'

const props = defineProps<{ text: string }>()

const blocks = computed(() => parseAssistantMarkdown(props.text))

const Inline: FunctionalComponent<{ segments: InlineSegment[] }> = ({ segments }) =>
  segments.map((segment) => {
    if (segment.kind === 'strong') return h('strong', segment.text)
    if (segment.kind === 'code') return h('code', segment.text)
    return createTextVNode(segment.text)
  })
Inline.props = ['segments']
</script>

<template>
  <div class="assistant-md" data-test="assistant-markdown">
    <template v-for="(block, index) in blocks" :key="index">
      <p v-if="block.kind === 'paragraph'" class="assistant-md__p">
        <template v-for="(line, lineIndex) in block.lines" :key="lineIndex">
          <br v-if="lineIndex > 0" />
          <Inline :segments="line" />
        </template>
      </p>
      <p v-else-if="block.kind === 'heading'" class="assistant-md__heading">
        <Inline :segments="block.segments" />
      </p>
      <ol
        v-else-if="block.kind === 'list' && block.ordered"
        class="assistant-md__list"
        :start="block.start"
      >
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <Inline :segments="item" />
        </li>
      </ol>
      <ul v-else-if="block.kind === 'list'" class="assistant-md__list">
        <li v-for="(item, itemIndex) in block.items" :key="itemIndex">
          <Inline :segments="item" />
        </li>
      </ul>
      <div
        v-else-if="block.kind === 'table'"
        class="assistant-md__table-wrap"
        tabindex="0"
        data-test="assistant-markdown-table"
      >
        <table class="assistant-md__table">
          <thead>
            <tr>
              <th
                v-for="(cell, cellIndex) in block.header"
                :key="cellIndex"
                scope="col"
                :style="block.align[cellIndex] ? { textAlign: block.align[cellIndex] } : undefined"
              >
                <Inline :segments="cell" />
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in block.rows" :key="rowIndex">
              <td
                v-for="(cell, cellIndex) in row"
                :key="cellIndex"
                :style="block.align[cellIndex] ? { textAlign: block.align[cellIndex] } : undefined"
              >
                <Inline :segments="cell" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <hr v-else-if="block.kind === 'rule'" class="assistant-md__rule" />
    </template>
  </div>
</template>

<style scoped>
.assistant-md {
  display: grid;
  gap: 8px;
  min-width: 0;
  white-space: normal;
}

.assistant-md__p,
.assistant-md__heading {
  margin: 0;
}

.assistant-md__heading {
  font-weight: 650;
}

.assistant-md__list {
  margin: 0;
  padding-left: 1.4em;
}

.assistant-md__list li + li {
  margin-top: 2px;
}

.assistant-md :deep(strong) {
  font-weight: 650;
}

.assistant-md :deep(code) {
  padding: 0 4px;
  border-radius: 4px;
  background: var(--well);
  font-family: var(--font-mono);
  font-size: 0.92em;
}

.assistant-md__table-wrap {
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.assistant-md__table-wrap:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.assistant-md__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  line-height: 1.45;
  font-variant-numeric: tabular-nums;
}

.assistant-md__table th,
.assistant-md__table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
  overflow-wrap: normal;
}

.assistant-md__table th {
  color: var(--ink-2);
  background: var(--well);
  font-weight: 600;
  white-space: nowrap;
}

.assistant-md__table td {
  min-width: 3em;
}

.assistant-md__table tbody tr:last-child td {
  border-bottom: 0;
}

.assistant-md__rule {
  width: 100%;
  margin: 2px 0;
  border: 0;
  border-top: 1px solid var(--line);
}
</style>
