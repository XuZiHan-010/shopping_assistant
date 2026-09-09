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

describe('版本感知提交：is_source_version/content_locale 显式判断（Task 11 gap closure）', () => {
  it('translationStatus 为 SOURCE（或未提供）时按源版本提交，不带 contentLocale', async () => {
    const calls: Array<[string, unknown]> = []
    const wrapper = mountEditor({
      document: {
        path: 'index/a.md',
        content: '原文',
        readOnly: false,
        version: 'v1',
        contentLocale: 'zh-CN',
        translationStatus: 'SOURCE',
      },
      save: async (content: string, _headers: Record<string, string>, options?: unknown) => {
        calls.push([content, options])
      },
    })
    await wrapper.find('textarea').setValue('改过的源正文')
    await wrapper.find('[data-testid="save"]').trigger('click')

    expect(calls[0]).toEqual(['改过的源正文', { isSourceVersion: true }])
  })

  it('translationStatus 为 CURRENT（正在编辑既有译文）时按译文提交，携带当前展示语言', async () => {
    useLocaleStore().setLocale('en-US')
    const calls: Array<[string, unknown]> = []
    const wrapper = mountEditor({
      document: {
        path: 'index/a.md',
        content: 'English translation',
        readOnly: false,
        version: 'v1',
        contentLocale: 'en-US',
        translationStatus: 'CURRENT',
      },
      save: async (content: string, _headers: Record<string, string>, options?: unknown) => {
        calls.push([content, options])
      },
    })
    await wrapper.find('[data-testid="save"]').trigger('click')

    expect(calls[0]).toEqual(['English translation', { isSourceVersion: false, contentLocale: 'en-US' }])
  })

  it('translationStatus 为 MISSING（请求译文但尚未保存过）时仍按译文提交，不会误判成编辑源正文', async () => {
    // 关键回归用例：MISSING 时后端把 content_locale 回退成源语言（zh-CN），
    // 如果这里改成"比较 document.contentLocale 和当前展示语言"来判断意图，
    // 会在这个状态下把它错判成"在编辑源正文"——保存时就会把源文档覆盖掉，
    // 而不是新建一份译文。必须用 translationStatus 本身来判断。
    useLocaleStore().setLocale('en-US')
    const calls: Array<[string, unknown]> = []
    const wrapper = mountEditor({
      document: {
        path: 'index/a.md',
        content: '原文（尚无英文译文，回退显示源正文）',
        readOnly: false,
        version: 'v1',
        contentLocale: 'zh-CN',
        translationStatus: 'MISSING',
      },
      save: async (content: string, _headers: Record<string, string>, options?: unknown) => {
        calls.push([content, options])
      },
    })
    await wrapper.find('textarea').setValue('New English translation')
    await wrapper.find('[data-testid="save"]').trigger('click')

    expect(calls[0]).toEqual([
      'New English translation',
      { isSourceVersion: false, contentLocale: 'en-US' },
    ])
  })

  it('translationStatus 为 STALE 时显示过期提示，未确认前保存按钮禁用', async () => {
    const calls: Array<[string, unknown]> = []
    const wrapper = mountEditor({
      document: {
        path: 'index/a.md',
        content: '源正文（译文已过期回退）',
        readOnly: false,
        version: 'v1',
        contentLocale: 'zh-CN',
        translationStatus: 'STALE',
      },
      save: async (content: string, _headers: Record<string, string>, options?: unknown) => {
        calls.push([content, options])
      },
    })

    expect(wrapper.find('[role="alert"]').text()).toContain('已过期')
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="save"]').trigger('click')
    expect(calls).toHaveLength(0)

    await wrapper.get('[data-testid="acknowledge-stale"]').trigger('click')
    expect(wrapper.find('[data-testid="acknowledge-stale"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeUndefined()

    await wrapper.find('[data-testid="save"]').trigger('click')
    expect(calls).toHaveLength(1)
  })

  it('切到另一份文档时，过期确认状态会重置', async () => {
    const wrapper = mountEditor({
      document: {
        path: 'index/a.md',
        content: '正文',
        readOnly: false,
        version: 'v1',
        contentLocale: 'zh-CN',
        translationStatus: 'STALE',
      },
    })
    await wrapper.get('[data-testid="acknowledge-stale"]').trigger('click')
    expect(wrapper.find('[data-testid="acknowledge-stale"]').exists()).toBe(false)

    await wrapper.setProps({
      document: {
        path: 'index/b.md',
        content: '另一份文档',
        readOnly: false,
        version: 'v1',
        contentLocale: 'zh-CN',
        translationStatus: 'STALE',
      },
    })

    expect(wrapper.find('[data-testid="acknowledge-stale"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeDefined()
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
