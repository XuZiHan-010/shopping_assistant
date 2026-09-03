import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import KnowledgeTree from './KnowledgeTree.vue'

function mountTree(props: Record<string, unknown>) {
  return mount(KnowledgeTree, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

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
        name: '客服工单',
        path: '业务/客服工单',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'v1',
        children: [
          {
            name: '业务流程',
            path: '业务/客服工单/业务流程',
            nodeType: 'directory',
            readOnly: false,
            size: 0,
            version: 'v1',
            children: [],
          },
        ],
      },
    ],
  },
]

describe('知识库目录树', () => {
  it('点击新建业务域按钮触发 create-domain 事件', async () => {
    const wrapper = mountTree({ roots })

    await wrapper.get('[data-testid="create-domain"]').trigger('click')

    expect(wrapper.emitted('create-domain')).toHaveLength(1)
  })

  it('当前选中节点带有 aria-current 标记', () => {
    const wrapper = mountTree({ roots, selectedPath: '业务/客服工单' })

    const selected = wrapper.get('[data-path="业务/客服工单"]')
    expect(selected.attributes('aria-current')).toBe('true')
    const notSelected = wrapper.get('[data-path="业务"]')
    expect(notSelected.attributes('aria-current')).toBeUndefined()
  })

  it('展示中文节点名称、目录标题与只读标记', () => {
    const readOnlyRoots: KnowledgeTreeNode[] = [
      {
        name: 'memory',
        path: 'memory',
        nodeType: 'directory',
        readOnly: true,
        size: 0,
        version: 'v1',
        children: [],
      },
    ]
    const wrapper = mountTree({ roots: readOnlyRoots })

    expect(wrapper.get('nav').attributes('aria-label')).toBe('知识库目录')
    expect(wrapper.text()).toContain('知识目录')
    expect(wrapper.text()).toContain('只读')
  })
})

describe('en-US 下确定性文案为英文，稳定 path 与已知业务域/固定板块展示名不混用中文', () => {
  beforeEach(() => {
    useLocaleStore().setLocale('en-US')
  })

  it('目录标题、新建业务域按钮与只读标记均为英文', () => {
    const readOnlyRoots: KnowledgeTreeNode[] = [
      {
        name: 'memory',
        path: 'memory',
        nodeType: 'directory',
        readOnly: true,
        size: 0,
        version: 'v1',
        children: [],
      },
    ]
    const wrapper = mountTree({ roots: readOnlyRoots })

    expect(wrapper.get('nav').attributes('aria-label')).toBe('Knowledge base directory')
    expect(wrapper.text()).toContain('Knowledge directory')
    expect(wrapper.get('[data-testid="create-domain"]').attributes('aria-label')).toBe(
      'New business domain',
    )
    expect(wrapper.text()).toContain('+ Domain')
    expect(wrapper.text()).toContain('Read-only')
  })

  it('业务根目录、已知业务域与固定板块展示为英文，稳定 path/data-path 保持中文原值不变', () => {
    const wrapper = mountTree({ roots })

    expect(wrapper.text()).toContain('Business')
    expect(wrapper.text()).toContain('Customer service tickets')
    expect(wrapper.text()).toContain('Business process')
    expect(wrapper.find('[data-path="业务"]').exists()).toBe(true)
    expect(wrapper.find('[data-path="业务/客服工单"]').exists()).toBe(true)
    expect(wrapper.find('[data-path="业务/客服工单/业务流程"]').exists()).toBe(true)
  })
})
