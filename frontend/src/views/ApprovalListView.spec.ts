import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import ApprovalListView from './ApprovalListView.vue'

const BASE_URL = 'http://127.0.0.1:8000'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function draftSummary(overrides: Record<string, unknown> = {}) {
  return {
    id: 'd-1',
    kind: 'RESTOCK',
    state: 'STAGED',
    title: '补货：测试商品 +60',
    draft_version: 1,
    target_version: 12,
    created_at: '2026-09-23T00:00:00Z',
    updated_at: '2026-09-23T00:00:00Z',
    expires_at: '2026-09-30T00:00:00Z',
    ...overrides,
  }
}

function draftDetailPayload(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    kind: 'CONTENT_CHANGE',
    state: 'STAGED',
    title: '商品内容更新',
    draft_version: 1,
    target_version: 1,
    created_at: '2026-09-23T00:00:00Z',
    updated_at: '2026-09-23T00:00:00Z',
    expires_at: '2026-09-30T00:00:00Z',
    diff: { entries: [] },
    guardrail_checks: [],
    guardrails_checked_at: '2026-09-23T00:00:00Z',
    approval_evidence: `evidence-${id}`,
    approval_evidence_expires_at: '2026-09-23T00:10:00Z',
    ...overrides,
  }
}

function applyResponsePayload(draftId: string) {
  return {
    draft: draftSummary({ id: draftId, state: 'APPLIED' }),
    ledger_entry: {
      id: `ledger-${draftId}`,
      draft_id: draftId,
      kind: 'CONTENT_CHANGE',
      drafted_by: { actor_type: 'AGENT', label: '经营助手' },
      approved_by: { actor_type: 'MERCHANT', label: '商家' },
      approved_at: '2026-09-23T00:05:00Z',
      applied_entry_ids: [`${draftId}:attributes`],
      guardrail_results: [],
    },
  }
}

async function mountList(listPayload: unknown) {
  const pinia = createPinia()
  setActivePinia(pinia)
  setChatTransport(createMockTransport({ chunkSizes: [16], stepDelayMs: 0 }))
  const auth = useAuthStore()
  await auth.loadMerchants()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValueOnce(
      jsonResponse({
        session_id: 'sid'.padEnd(43, '0'),
        role: 'MERCHANT',
        expires_at: '2026-09-24T00:00:00Z',
        merchant_display_name: 'Borough商家100',
      }),
    ),
  )
  await auth.openSession(auth.merchants[0]!)

  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(listPayload))
  vi.stubGlobal('fetch', fetchMock)

  const wrapper = mount(ApprovalListView, {
    global: {
      plugins: [pinia, i18n],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()
  return { wrapper, fetchMock, pinia }
}

beforeEach(() => {
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('ApprovalListView', () => {
  it('按 batchId 分组展示；同批次的子草稿归在一个分组标题下', async () => {
    const { wrapper } = await mountList({
      items: [
        draftSummary({ id: 'd-b1-a', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
        draftSummary({ id: 'd-b1-b', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
        draftSummary({ id: 'd-solo', title: '独立草稿' }),
      ],
      next_cursor: null,
      has_more: false,
    })

    const groups = wrapper.findAll('[data-test=draft-group]')
    expect(groups).toHaveLength(2)
  })

  it('只勾选批次里的部分子草稿时，批准所选只对勾选的那些发起应用', async () => {
    const { wrapper, fetchMock } = await mountList({
      items: [
        draftSummary({ id: 'd-b1-a', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
        draftSummary({ id: 'd-b1-b', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
      ],
      next_cursor: null,
      has_more: false,
    })

    fetchMock.mockImplementation((url: string) => {
      if (url.includes('d-b1-a') && !url.includes('apply')) {
        return Promise.resolve(jsonResponse(draftDetailPayload('d-b1-a')))
      }
      if (url.includes('d-b1-a') && url.includes('apply')) {
        return Promise.resolve(jsonResponse(applyResponsePayload('d-b1-a')))
      }
      throw new Error(`unexpected fetch for other draft: ${url}`)
    })

    await wrapper.get('[data-test=select-d-b1-a]').setValue(true)
    await wrapper.get('[data-test=approve-selected]').trigger('click')
    await flushPromises()

    const applyCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/apply'))
    expect(applyCalls).toHaveLength(1)
    expect(applyCalls[0]![0]).toContain('d-b1-a')
  })

  it('批准整批（全部勾选）对批次里每个 STAGED 子草稿都发起应用', async () => {
    const { wrapper, fetchMock } = await mountList({
      items: [
        draftSummary({ id: 'd-b1-a', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
        draftSummary({ id: 'd-b1-b', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
      ],
      next_cursor: null,
      has_more: false,
    })

    fetchMock.mockImplementation((url: string) => {
      const id = url.includes('d-b1-a') ? 'd-b1-a' : 'd-b1-b'
      if (url.includes('/apply')) {
        return Promise.resolve(jsonResponse(applyResponsePayload(id)))
      }
      return Promise.resolve(jsonResponse(draftDetailPayload(id)))
    })

    await wrapper.get('[data-test=select-all-batch-1]').setValue(true)
    await wrapper.get('[data-test=approve-selected]').trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()

    const applyCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/apply'))
    expect(applyCalls).toHaveLength(2)
  })

  it('不勾选任何草稿时批准按钮禁用', async () => {
    const { wrapper } = await mountList({
      items: [draftSummary({ id: 'd-solo' })],
      next_cursor: null,
      has_more: false,
    })

    const button = wrapper.get('[data-test=approve-selected]')
    expect((button.element as HTMLButtonElement).disabled).toBe(true)
  })
})
