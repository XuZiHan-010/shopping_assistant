import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'

import { i18n } from '@/i18n'
import { useSignalsStore } from '@/stores/signals'
import SignalsView from './SignalsView.vue'

it('requires a reason before ignoring a signal', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useSignalsStore()
  vi.spyOn(store, 'load').mockResolvedValue()
  const ignore = vi.spyOn(store, 'ignore').mockResolvedValue()
  store.items = [{
    id: 'signal-1', kind: 'RETURN_REQUESTS', productId: 'product-1',
    productName: '围巾', signalDate: '2026-09-25', count: 2,
    isIgnored: false, ignoreReason: null,
  }]
  const wrapper = mount(SignalsView, { global: { plugins: [pinia, i18n] } })
  const button = wrapper.get('button')
  expect(button.attributes('disabled')).toBeDefined()
  await wrapper.get('input[type="text"]').setValue('已处理')
  expect(button.attributes('disabled')).toBeUndefined()
  await button.trigger('click')
  expect(ignore).toHaveBeenCalledWith('signal-1', '已处理')
})
