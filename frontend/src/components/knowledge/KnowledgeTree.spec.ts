import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'

import KnowledgeTree from './KnowledgeTree.vue'

const roots: KnowledgeTreeNode[] = [
  {
    name: '业务',
    path: '业务',
    nodeType: 'directory',
    readOnly: false,
    size: 0,
    version: 'v1',
    children: [
      {
        name: '客服',
        path: '业务/客服',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'v1',
        children: [],
      },
    ],
  },
]

describe('知识库目录树', () => {
  it('点击新建业务域按钮触发 create-domain 事件', async () => {
    const wrapper = mount(KnowledgeTree, { props: { roots } })

    await wrapper.get('[data-testid="create-domain"]').trigger('click')

    expect(wrapper.emitted('create-domain')).toHaveLength(1)
  })

  it('当前选中节点带有 aria-current 标记', () => {
    const wrapper = mount(KnowledgeTree, { props: { roots, selectedPath: '业务/客服' } })

    const selected = wrapper.get('[data-path="业务/客服"]')
    expect(selected.attributes('aria-current')).toBe('true')
    const notSelected = wrapper.get('[data-path="业务"]')
    expect(notSelected.attributes('aria-current')).toBeUndefined()
  })
})
