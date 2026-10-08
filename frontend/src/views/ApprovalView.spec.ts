import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useDraftsStore } from '@/stores/drafts'

import ApprovalView from './ApprovalView.vue'

const BASE_URL = 'http://127.0.0.1:8000'
const DRAFT_ID = 'd-1'
const EVIDENCE = 'evidence-token-abc123'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorResponse(code: string, status: number, details: unknown = []): Response {
  return jsonResponse(
    { code, message: 'boom', request_id: 'req-1', details, retryable: false },
    status,
  )
}

function draftDetailPayload(overrides: Record<string, unknown> = {}) {
  return {
    id: DRAFT_ID,
    kind: 'RESTOCK',
    state: 'STAGED',
    title: '补货：测试商品 +60',
    draft_version: 1,
    target_version: 12,
    created_at: '2026-09-23T00:00:00Z',
    updated_at: '2026-09-23T00:00:00Z',
    expires_at: '2026-09-30T00:00:00Z',
    diff: {
      entries: [
        {
          entry_id: 'd-1:stock_on_hand',
          target_type: 'PRODUCT',
          target_id: 'p-1',
          field: 'stock_on_hand',
          unit: 'COUNT',
          before: 12,
          after: 72,
          is_preview: false,
        },
      ],
    },
    guardrail_checks: [
      { code: 'RESTOCK_DELTA_EXCEEDS_LIMIT', passed: true, current_limit: null, remediation: null },
    ],
    guardrails_checked_at: '2026-09-23T00:00:00Z',
    approval_evidence: EVIDENCE,
    approval_evidence_expires_at: '2026-09-23T00:10:00Z',
    ...overrides,
  }
}

async function mountApproval(detailOverrides: Record<string, unknown> = {}) {
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

  const fetchMock = vi.fn().mockResolvedValue(jsonResponse(draftDetailPayload(detailOverrides)))
  vi.stubGlobal('fetch', fetchMock)

  const wrapper = mount(ApprovalView, {
    props: { draftId: DRAFT_ID },
    global: { plugins: [pinia, i18n] },
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

describe('ApprovalView', () => {
  it('展示完整 diff、草案版本、目标版本与护栏预检说明', async () => {
    const { wrapper } = await mountApproval()

    const row = wrapper.get('[data-test=diff-row]')
    expect(row.text()).toContain('stock_on_hand')
    expect(row.findAll('td').map((cell) => cell.text())).toEqual(['stock_on_hand', '12', '72'])
    expect(wrapper.get('[data-test=draft-version]').text()).toBe('1')
    expect(wrapper.get('[data-test=target-version]').text()).toBe('12')
    expect(wrapper.text()).toContain('应用时将按当时生效的配置重新检查')
    expect(wrapper.find('[data-test=approve]').exists()).toBe(true)
  })

  it('护栏不通过时批准按钮禁用', async () => {
    const { wrapper } = await mountApproval({
      guardrail_checks: [
        {
          code: 'RESTOCK_DELTA_EXCEEDS_LIMIT',
          passed: false,
          current_limit: '单次补货不超过 50 件',
          remediation: '减少补货数量后重新起草',
        },
      ],
    })

    expect(wrapper.get('[data-test=approve]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('减少补货数量后重新起草')
  })

  it('审批证据不进入 Pinia Store', async () => {
    await mountApproval()

    expect(JSON.stringify(useDraftsStore().$state)).not.toContain(EVIDENCE)
  })

  it('网络重试复用同一 client_request_id', async () => {
    const { wrapper, fetchMock } = await mountApproval()
    let applyCallCount = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && String(url).includes('/apply')) {
        applyCallCount += 1
        if (applyCallCount === 1) throw new TypeError('network down')
        return jsonResponse({
          draft: { ...draftDetailPayload(), state: 'APPLIED' },
          ledger_entry: {
            id: 'l-1',
            draft_id: DRAFT_ID,
            kind: 'RESTOCK',
            drafted_by: { actor_type: 'AGENT', label: '经营助手' },
            approved_by: { actor_type: 'MERCHANT', label: '商家' },
            approved_at: '2026-09-23T00:05:00Z',
            applied_entry_ids: ['d-1:stock_on_hand'],
            guardrail_results: [],
          },
        })
      }
      return jsonResponse(draftDetailPayload())
    })

    await wrapper.get('[data-test=approve]').trigger('click')
    await flushPromises()

    const applyCalls = fetchMock.mock.calls.filter(
      ([url, init]) => init?.method === 'POST' && String(url).includes('/apply'),
    )
    expect(applyCalls).toHaveLength(2)
    const ids = applyCalls.map(([, init]) => JSON.parse(init!.body as string).client_request_id)
    expect(new Set(ids).size).toBe(1)
  })

  it('CONFIRMATION_REQUIRED 时重新拉取详情且不自动重试应用', async () => {
    const { wrapper, fetchMock } = await mountApproval()
    let getDraftCalls = 0
    let applyCalls = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && String(url).includes('/apply')) {
        applyCalls += 1
        return errorResponse('CONFIRMATION_REQUIRED', 422)
      }
      getDraftCalls += 1
      return jsonResponse(draftDetailPayload())
    })

    await wrapper.get('[data-test=approve]').trigger('click')
    await flushPromises()

    expect(applyCalls).toBe(1)
    // mock 在挂载完成后才被替换，只统计点击批准之后发生的详情请求：
    // 应该恰好一次——CONFIRMATION_REQUIRED 触发的那次重新拉取。
    expect(getDraftCalls).toBe(1)
    expect(wrapper.text()).toContain('请核对后重新批准')
  })

  it('VERSION_CONFLICT 时提示库存已变化，不自动重试', async () => {
    const { wrapper, fetchMock } = await mountApproval()
    let applyCalls = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && String(url).includes('/apply')) {
        applyCalls += 1
        return errorResponse('VERSION_CONFLICT', 409, [{ scope: 'TARGET' }])
      }
      return jsonResponse(draftDetailPayload())
    })

    await wrapper.get('[data-test=approve]').trigger('click')
    await flushPromises()

    expect(applyCalls).toBe(1)
    expect(wrapper.text()).toContain('请刷新页面并重新确认')
  })
})
