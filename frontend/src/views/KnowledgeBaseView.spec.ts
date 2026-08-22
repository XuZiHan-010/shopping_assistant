import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AppError } from '@/api/errors'
import { setChatTransport } from '@/api/transport'

import KnowledgeBaseView from './KnowledgeBaseView.vue'

describe('KnowledgeBaseView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    setChatTransport(undefined)
  })

  it('无效管理员令牌后保留输入入口，允许直接重试', async () => {
    setChatTransport(async () => {
      throw new AppError('AUTH_REQUIRED', '管理员令牌无效', { status: 401 })
    })
    const wrapper = mount(KnowledgeBaseView, { global: { plugins: [createPinia()] } })

    await wrapper.get('input').setValue('bad-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('input').exists()).toBe(true)
    expect(wrapper.text()).toContain('管理员令牌无效')
  })
})
