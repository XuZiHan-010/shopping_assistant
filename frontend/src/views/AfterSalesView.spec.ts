import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'

import { i18n } from '@/i18n'
import { routes } from '@/router'
import { useAfterSalesStore } from '@/stores/afterSales'
import { useOpsChatStore } from '@/stores/opsChat'
import AfterSalesView from './AfterSalesView.vue'

it('shows alias and summary, and only prefills the assistant without submitting or approving', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useAfterSalesStore()
  vi.spyOn(store, 'load').mockResolvedValue()
  store.detail = {
    id: 'sale-1', orderId: 'order-1', type: 'TICKET', state: 'PENDING_MERCHANT',
    refundAmountCents: null, buyerAlias: '顾客 #abcd1234',
    firstResponseDueAt: '2026-09-26T00:00:00Z', createdAt: '2026-09-25T00:00:00Z',
    reason: '商品有瑕疵', lines: [], events: [], supplements: [], replies: [],
    conversationSummary: { status: 'AVAILABLE', text: '商品有瑕疵', unavailableReason: null },
  }
  const chat = useOpsChatStore()
  const prefill = vi.spyOn(chat, 'prefill')
  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push('/after-sales')
  await router.isReady()
  vi.spyOn(router, 'push').mockResolvedValue(undefined)
  const wrapper = mount(AfterSalesView, { global: { plugins: [pinia, i18n, router] } })
  expect(wrapper.text()).toContain('顾客 #abcd1234')
  expect(wrapper.text()).toContain('商品有瑕疵')
  expect(wrapper.text()).not.toContain('buyer_key')
  expect(wrapper.text()).not.toContain('完整对话')
  await wrapper.get('[data-test="draft-after-sale"]').trigger('click')
  await flushPromises()
  expect(prefill).toHaveBeenCalledOnce()
  expect(prefill.mock.calls[0]?.[0]).toContain('sale-1')
})
