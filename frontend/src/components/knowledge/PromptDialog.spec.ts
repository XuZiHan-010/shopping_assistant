import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useLocaleStore } from '@/stores/locale'

import PromptDialog from './PromptDialog.vue'

function mountDialog(props: Record<string, unknown>) {
  return mount(PromptDialog, { props, global: { plugins: [i18n] } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  useLocaleStore().setLocale('zh-CN')
})

describe('知识库命名对话框', () => {
  it('提交时携带输入值并清空输入框', async () => {
    const wrapper = mountDialog({ title: '新建文档', label: '文档名称' })

    await wrapper.get('input').setValue('订单履约口径.md')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]).toEqual(['订单履约口径.md'])
  })

  it('空白输入不触发提交', async () => {
    const wrapper = mountDialog({ title: '新建业务域', label: '业务域名称' })

    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('点击取消触发 cancel 事件', async () => {
    const wrapper = mountDialog({ title: '新建文档', label: '文档名称' })

    await wrapper.get('[data-testid="cancel"]').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('展示传入的错误信息且不清空输入', async () => {
    const wrapper = mountDialog({
      title: '新建文档',
      label: '文档名称',
      errorMessage: '同名文档已存在',
    })
    await wrapper.get('input').setValue('已存在.md')

    expect(wrapper.text()).toContain('同名文档已存在')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('已存在.md')
  })

  it('提交中禁用提交按钮', () => {
    const wrapper = mountDialog({ title: '新建文档', label: '文档名称', pending: true })

    expect(wrapper.get('[data-testid="submit"]').attributes('disabled')).toBeDefined()
  })

  it('支持初始值，便于重命名场景预填当前名称', () => {
    const wrapper = mountDialog({
      title: '重命名业务域',
      label: '业务域名称',
      initialValue: '客服',
    })

    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('客服')
  })
})

describe('en-US 下确定性按钮文案为英文', () => {
  beforeEach(() => {
    useLocaleStore().setLocale('en-US')
  })

  it('默认取消/确认按钮与处理中态均为英文，传入的 title/label 保持原样不重译', () => {
    const wrapper = mountDialog({ title: 'New document', label: 'Document name' })

    expect(wrapper.get('[data-testid="cancel"]').text()).toBe('Cancel')
    expect(wrapper.get('[data-testid="submit"]').text()).toBe('Confirm')
    expect(wrapper.text()).toContain('New document')
    expect(wrapper.text()).toContain('Document name')
  })

  it('提交中展示英文处理中文案', () => {
    const wrapper = mountDialog({ title: 'New document', label: 'Document name', pending: true })

    expect(wrapper.get('[data-testid="submit"]').text()).toBe('Processing…')
  })

  it('自定义 submitLabel 优先于默认英文文案', () => {
    const wrapper = mountDialog({
      title: 'Rename business domain',
      label: 'Business domain name',
      submitLabel: 'Rename',
    })

    expect(wrapper.get('[data-testid="submit"]').text()).toBe('Rename')
  })
})
