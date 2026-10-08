import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import MerchantMemoryView from './MerchantMemoryView.vue'

const fetchMemories = vi.fn()
const deleteMemory = vi.fn()
vi.mock('@/api/adapters/merchantMemory', () => ({
  fetchMerchantMemories: (...args: unknown[]) => fetchMemories(...args),
  deleteMerchantMemory: (...args: unknown[]) => deleteMemory(...args),
}))
vi.mock('@/stores/auth', () => ({
  registerSessionScopedReset: () => () => undefined,
  useAuthStore: () => ({ callWithSessionRetry: (fn: (sid: string) => Promise<unknown>) => fn('session-1') }),
}))

it('separates fact deletion from read-only summaries and announces rebuild', async () => {
  fetchMemories.mockResolvedValue({
    facts: [{ id: 'f-1', layer: 'FACT', category: 'tone', content: '偏正式',
      sourceRef: { conversationId: 'c-1', messageId: 'm-1' }, updatedAt: '2026-09-28T00:00:00Z' }],
    nextCursor: null,
    summaries: [{ id: 's-1', layer: 'SUMMARY', category: 'tone', content: '偏正式总结',
      sourceRef: null, updatedAt: '2026-09-28T00:00:00Z' }],
  })
  fetchMemories.mockResolvedValueOnce({
    facts: [{ id: 'f-1', layer: 'FACT', category: 'tone', content: '偏正式',
      sourceRef: { conversationId: 'c-1', messageId: 'm-1' }, updatedAt: '2026-09-28T00:00:00Z' }],
    nextCursor: null,
    summaries: [{ id: 's-1', layer: 'SUMMARY', category: 'tone', content: '偏正式总结',
      sourceRef: null, updatedAt: '2026-09-28T00:00:00Z' }],
  }).mockResolvedValueOnce({ facts: [], nextCursor: null, summaries: [] })
  deleteMemory.mockResolvedValue({ deleted_id: 'f-1', summary_rebuild_scheduled: true })
  const wrapper = mount(MerchantMemoryView, {
    global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  expect(wrapper.text()).toContain('偏正式总结')
  expect(wrapper.findAll('button')).toHaveLength(1)
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(deleteMemory).toHaveBeenCalledWith('session-1', 'f-1')
  expect(wrapper.text()).toContain('相关总结将重新生成')
  expect(wrapper.text()).not.toContain('偏正式总结')
})
