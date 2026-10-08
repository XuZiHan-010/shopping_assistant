import { readFileSync } from 'node:fs'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'

import {
  applyDraft,
  discardDraft,
  fetchDailyBrief,
  fetchDraftDetail,
  fetchDrafts,
  fetchInventoryAlerts,
  regenerateDailyBrief,
} from './merchantOps'

const BASE_URL = 'http://127.0.0.1:8000'
const SESSION = 's'.repeat(43)

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function errorResponse(code: string, status: number): Response {
  return jsonResponse(
    { code, message: 'boom', request_id: 'req-1', details: [], retryable: false },
    status,
  )
}

function alert(overrides: Record<string, unknown> = {}) {
  return {
    id: 'LOW_STOCK:p-1',
    kind: 'LOW_STOCK',
    product_id: 'p-1',
    product_name: '测试商品',
    stock_on_hand: 6,
    stock_reserved: 2,
    stock_available: 4,
    low_stock_threshold: 5,
    sold_last_30d: 12,
    days_of_supply: 10,
    ...overrides,
  }
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

describe('merchantOps adapter', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('fetchInventoryAlerts 转成领域类型并带上会话头', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ items: [alert()], next_cursor: 'cur-1', has_more: true }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const page = await fetchInventoryAlerts(SESSION, { limit: 20 })

    expect(page.items[0]).toEqual({
      id: 'LOW_STOCK:p-1',
      kind: 'LOW_STOCK',
      productId: 'p-1',
      productName: '测试商品',
      stockOnHand: 6,
      stockReserved: 2,
      stockAvailable: 4,
      lowStockThreshold: 5,
      soldLast30d: 12,
      daysOfSupply: 10,
    })
    expect(page.nextCursor).toBe('cur-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/inventory/alerts?limit=20`)
    expect((init.headers as Record<string, string>)['X-Session-Id']).toBe(SESSION)
  })

  it('可售天数为 null 时原样保留，不折成 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [alert({ sold_last_30d: 0, days_of_supply: null })],
          next_cursor: null,
          has_more: false,
        }),
      ),
    )

    const page = await fetchInventoryAlerts(SESSION)

    expect(page.items[0].daysOfSupply).toBeNull()
  })

  it('空查询参数不出现在 URL 里', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [], next_cursor: null, has_more: false }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchDrafts(SESSION, { cursor: null })

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/api/v2/merchant/drafts`)
  })

  it('batchId 转成 URL 查询参数（按批次分组查看商品内容批量草稿）', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ items: [], next_cursor: null, has_more: false }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchDrafts(SESSION, { batchId: 'batch-1' })

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/api/v2/merchant/drafts?batch_id=batch-1`)
  })

  it('DraftSummary 带出 batchId；无批次的草稿 batchId 为 null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [
            draftSummary({ id: 'd-batch', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
            draftSummary({ id: 'd-solo' }),
          ],
          next_cursor: null,
          has_more: false,
        }),
      ),
    )

    const page = await fetchDrafts(SESSION)

    expect(page.items[0].batchId).toBe('batch-1')
    expect(page.items[1].batchId).toBeNull()
  })

  it('游标失效转成 INVALID_CURSOR 的 AppError，且不可重试', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse('INVALID_CURSOR', 422)))

    const error = await fetchDrafts(SESSION, { cursor: 'stale' }).catch((cause) => cause)

    expect(error).toBeInstanceOf(AppError)
    expect((error as AppError).code).toBe('INVALID_CURSOR')
  })

  it('fetchDraftDetail 带出审批证据与差异条目', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          ...draftSummary(),
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
            {
              code: 'RESTOCK_DELTA_EXCEEDS_LIMIT',
              passed: true,
              current_limit: null,
              remediation: null,
            },
          ],
          guardrails_checked_at: '2026-09-23T00:00:00Z',
          approval_evidence: 'evidence.token',
          approval_evidence_expires_at: '2026-09-23T00:10:00Z',
        }),
      ),
    )

    const detail = await fetchDraftDetail(SESSION, 'd-1')

    expect(detail.approvalEvidence).toBe('evidence.token')
    expect(detail.diff[0]).toMatchObject({ field: 'stock_on_hand', before: 12, after: 72 })
    expect(detail.guardrailChecks[0].code).toBe('RESTOCK_DELTA_EXCEEDS_LIMIT')
  })

  it('详情请求不走 HTTP 缓存——证据是一次性的', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        ...draftSummary(),
        diff: { entries: [] },
        guardrail_checks: [],
        guardrails_checked_at: '2026-09-23T00:00:00Z',
        approval_evidence: 'evidence.token',
        approval_evidence_expires_at: '2026-09-23T00:10:00Z',
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await fetchDraftDetail(SESSION, 'd-1')

    expect(fetchMock.mock.calls[0][1].cache).toBe('no-store')
  })

  it('applyDraft 原样回传证据，请求体用后端字段名', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        draft: draftSummary({ state: 'APPLIED' }),
        ledger_entry: {
          id: 'l-1',
          draft_id: 'd-1',
          kind: 'RESTOCK',
          drafted_by: { actor_type: 'AGENT', label: '经营助手' },
          approved_by: { actor_type: 'MERCHANT', label: '商家' },
          approved_at: '2026-09-23T00:05:00Z',
          applied_entry_ids: ['d-1:stock_on_hand'],
          guardrail_results: [
            {
              code: 'RESTOCK_DELTA_EXCEEDS_LIMIT',
              passed: true,
              current_limit: null,
              remediation: null,
            },
          ],
        },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const applied = await applyDraft(SESSION, 'd-1', {
      clientRequestId: 'req-1',
      draftVersion: 1,
      targetVersion: 12,
      approvalEvidence: 'evidence.token',
    })

    expect(applied.draft.state).toBe('APPLIED')
    expect(applied.ledgerEntry.approvedBy.actorType).toBe('MERCHANT')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body).toEqual({
      client_request_id: 'req-1',
      draft_version: 1,
      target_version: 12,
      approval_evidence: 'evidence.token',
    })
  })

  it('未勾选条目时不发送 accepted_entry_ids（null 表示批准全部）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(errorResponse('VERSION_CONFLICT', 409))
    vi.stubGlobal('fetch', fetchMock)

    await applyDraft(SESSION, 'd-1', {
      clientRequestId: 'req-1',
      draftVersion: 1,
      targetVersion: 12,
      approvalEvidence: 'evidence.token',
    }).catch(() => undefined)

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect('accepted_entry_ids' in body).toBe(false)
  })

  it('证据失效转成 CONFIRMATION_REQUIRED，界面据此重新取详情', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse('CONFIRMATION_REQUIRED', 422)))

    const error = await applyDraft(SESSION, 'd-1', {
      clientRequestId: 'req-1',
      draftVersion: 1,
      targetVersion: 12,
      approvalEvidence: 'stale.token',
    }).catch((cause) => cause)

    expect((error as AppError).code).toBe('CONFIRMATION_REQUIRED')
  })

  it('discardDraft 发 DELETE 且不带请求体', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await discardDraft(SESSION, 'd-1')

    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE')
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined()
  })

  it('fetchDailyBrief 保留降级字段与确定性来源标注', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
          thinking_steps: [],
          quality_status: 'NOT_RUN',
          quality_attempts: 0,
          quality_notes: [],
          degraded: false,
          degraded_reason: null,
          brief_version: 1,
          business_date: '2026-09-23',
          business_timezone: 'Asia/Shanghai',
          data_as_of: '2026-09-23T00:00:00Z',
          generated_at: '2026-09-23T00:00:00Z',
          trigger: 'SCHEDULED',
          items: [
            {
              rank: 1,
              kind: 'INVENTORY_ALERT',
              title: '已售罄：测试商品',
              evidence: '商品 p-1：在库 0',
              amount_cents: null,
              next_action_prompt: '给「测试商品」起草一份补货草稿',
            },
          ],
          collapsed_count: 0,
        }),
      ),
    )

    const brief = await fetchDailyBrief(SESSION)

    expect(brief.analysisSources).toEqual([
      { source: 'DATABASE', degraded: false, degradedReason: null },
    ])
    expect(brief.degraded).toBe(false)
    expect(brief.items[0].nextActionPrompt).toContain('起草')
  })

  it('Adapter 不对金额做浮点除法（金额只在渲染层用 localizedFormat 转换）', () => {
    const src = readFileSync('src/api/adapters/merchantOps.ts', 'utf-8')
    expect(src).not.toMatch(/_cents\s*\/\s*100/)
  })

  it('regenerateDailyBrief 带 client_request_id 请求体、返回新版本简报', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        analysis_sources: [{ source: 'DATABASE', degraded: false, degraded_reason: null }],
        thinking_steps: [],
        quality_status: 'NOT_RUN',
        quality_attempts: 0,
        quality_notes: [],
        degraded: false,
        degraded_reason: null,
        brief_version: 2,
        business_date: '2026-09-26',
        business_timezone: 'Asia/Shanghai',
        data_as_of: '2026-09-26T00:00:00Z',
        generated_at: '2026-09-26T00:00:00Z',
        trigger: 'REGENERATED',
        items: [],
        collapsed_count: 0,
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const brief = await regenerateDailyBrief(SESSION, 'regen-1')

    expect(brief.briefVersion).toBe(2)
    expect(brief.trigger).toBe('REGENERATED')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE_URL}/api/v2/merchant/briefs/daily/current/regenerate`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ client_request_id: 'regen-1' })
  })

  it('冷却期内重新生成转成 RATE_LIMITED 的 AppError，且可重试', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(errorResponse('RATE_LIMITED', 429)))

    const error = await regenerateDailyBrief(SESSION, 'regen-2').catch((cause) => cause)

    expect(error).toBeInstanceOf(AppError)
    expect((error as AppError).code).toBe('RATE_LIMITED')
  })
})
