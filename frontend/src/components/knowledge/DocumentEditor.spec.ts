import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DocumentEditor from './DocumentEditor.vue'

describe('知识文档编辑器', () => {
  it('memory 文档只读且不显示保存按钮', () => {
    const wrapper = mount(DocumentEditor, {
      props: {
        document: {
          path: 'memory/merchants/abc/TRADE.md',
          content: 'x',
          readOnly: true,
          version: 'v1',
        },
      },
    })

    expect(wrapper.find('textarea').attributes('readonly')).toBeDefined()
    expect(wrapper.find('[data-testid="save"]').exists()).toBe(false)
  })

  it('412 冲突时提示重新加载且不丢失用户输入', async () => {
    const wrapper = mount(DocumentEditor, {
      props: { document: { path: 'index/a.md', content: '原文', readOnly: false, version: 'v1' } },
    })
    await wrapper.find('textarea').setValue('我改的内容')
    await wrapper.vm.handleConflict()

    expect(wrapper.text()).toContain('已被其他维护者修改')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('我改的内容')
  })

  it('保存时带上当前版本作为 If-Match', async () => {
    const calls: Array<Record<string, string>> = []
    const wrapper = mount(DocumentEditor, {
      props: {
        document: { path: 'index/a.md', content: '原文', readOnly: false, version: 'v1' },
        save: async (_: string, headers: Record<string, string>) => {
          calls.push(headers)
        },
      },
    })
    await wrapper.find('[data-testid="save"]').trigger('click')

    expect(calls[0]?.['If-Match']).toBe('"v1"')
  })
})
