import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import DocumentEditor from './DocumentEditor.vue'

function mountEditor(props: Record<string, unknown>) {
  return mount(DocumentEditor, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('知识文档编辑器', () => {
  it('memory 文档只读且不显示保存按钮', () => {
    const wrapper = mountEditor({
      document: {
        path: 'memory/merchants/abc/TRADE.md',
        content: 'x',
        readOnly: true,
        version: 'v1',
      },
    })

    expect(wrapper.find('textarea').attributes('readonly')).toBeDefined()
    expect(wrapper.find('[data-testid="save"]').exists()).toBe(false)
  })

  it('412 冲突时提示重新加载且不丢失用户输入', async () => {
    const wrapper = mountEditor({
      document: { path: 'index/a.md', content: '原文', readOnly: false, version: 'v1' },
    })
    await wrapper.find('textarea').setValue('我改的内容')
    await wrapper.vm.handleConflict()

    expect(wrapper.text()).toContain('已被其他维护者修改')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('我改的内容')
  })

  it('保存时带上当前版本作为 If-Match', async () => {
    const calls: Array<Record<string, string>> = []
    const wrapper = mountEditor({
      document: { path: 'index/a.md', content: '原文', readOnly: false, version: 'v1' },
      save: async (_: string, headers: Record<string, string>) => {
        calls.push(headers)
      },
    })
    await wrapper.find('[data-testid="save"]').trigger('click')

    expect(calls[0]?.['If-Match']).toBe('"v1"')
  })
})

describe('en-US 下确定性文案为英文', () => {
  beforeEach(() => {
    useLocaleStore().setLocale('en-US')
  })

  it('只读记忆徽标、内容 aria-label 与保存按钮均为英文，稳定 path 原样展示', () => {
    const wrapper = mountEditor({
      document: {
        path: 'memory/merchants/abc/TRADE.md',
        content: 'x',
        readOnly: true,
        version: 'v1',
      },
    })

    expect(wrapper.text()).toContain('Memory (read-only)')
    expect(wrapper.get('textarea').attributes('aria-label')).toBe(
      'memory/merchants/abc/TRADE.md content',
    )
    expect(wrapper.text()).toContain('memory/merchants/abc/TRADE.md')
  })

  it('可编辑文档展示英文保存按钮', () => {
    const wrapper = mountEditor({
      document: { path: 'index/a.md', content: 'source text', readOnly: false, version: 'v1' },
    })

    expect(wrapper.get('[data-testid="save"]').text()).toBe('Save changes')
  })

  it('412 冲突时展示英文提示且不丢失用户输入', async () => {
    const wrapper = mountEditor({
      document: { path: 'index/a.md', content: 'source text', readOnly: false, version: 'v1' },
    })
    await wrapper.find('textarea').setValue('my edited content')
    await wrapper.vm.handleConflict()

    expect(wrapper.text()).toContain('This document was modified by another maintainer')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe(
      'my edited content',
    )
  })
})
