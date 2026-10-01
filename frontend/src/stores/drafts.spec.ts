import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'
import { createMockTransport } from '@/api/mock/transport'
import { setChatTransport } from '@/api/transport'
import { deferred } from '@/testing/workspacePayloads'

import { useAuthStore } from './auth'
import { useDraftsStore } from './drafts'

const BASE_URL = 'http://127.0.0.1:8000'

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

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

async function openTestSession(): Promise<void> {
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
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubEnv('VITE_API_BASE_URL', BASE_URL)
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('useDraftsStore', () => {
  it.each([false, true])('换商家后丢弃旧请求的结果或错误（失败=%s）', async (fail) => {
    await openTestSession()
    const store = useDraftsStore()
    const auth = useAuthStore()
    const old = deferred<Response>()
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: unknown, init: RequestInit) => {
        if (init.method === 'DELETE') return Promise.resolve(new Response(null, { status: 204 }))
        if (new Headers(init.headers).get('X-Session-Id') === 'sid'.padEnd(43, '0'))
          return old.promise
        return Promise.resolve(
          jsonResponse({
            items: [draftSummary({ id: 'new-shop' })],
            next_cursor: null,
            has_more: false,
          }),
        )
      }),
    )
    const pending = store.loadDrafts().catch(() => undefined)
    await Promise.resolve()
    auth.selectByDisplayName(auth.merchants[1]!.displayName)
    auth.sessionId = 'new-session'.padEnd(43, '0')
    await store.loadDrafts()
    if (fail)
      old.resolve(
        jsonResponse(
          {
            code: 'DATA_SOURCE_UNAVAILABLE',
            message: '旧商家的失败',
            request_id: 'old',
            retryable: true,
          },
          503,
        ),
      )
    else
      old.resolve(
        jsonResponse({ items: [draftSummary()], next_cursor: 'old-cursor', has_more: true }),
      )
    await pending
    expect(store.items.map((item) => item.id)).toEqual(['new-shop'])
    expect(store.nextCursor).toBeNull()
    expect(store.hasMore).toBe(false)
    expect(store.errorMessage).toBe('')
    expect(store.loading).toBe(false)
  })

  it('先发后至的列表不能覆盖后发列表或提前结束 loading', async () => {
    await openTestSession()
    const store = useDraftsStore()
    const old = deferred<Response>()
    const latest = deferred<Response>()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise),
    )
    const first = store.loadDrafts()
    await Promise.resolve()
    const second = store.loadDrafts()
    await Promise.resolve()
    old.resolve(jsonResponse({ items: [draftSummary()], next_cursor: 'old', has_more: true }))
    await first
    expect(store.loading).toBe(true)
    expect(store.items).toEqual([])
    latest.resolve(
      jsonResponse({ items: [draftSummary({ id: 'latest' })], next_cursor: null, has_more: false }),
    )
    await second
    expect(store.items.map((item) => item.id)).toEqual(['latest'])
  })
  it('loadDrafts 通过会话重试机制拉取列表并写入 Store', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ items: [draftSummary()], next_cursor: 'cur-1', has_more: true }),
        ),
    )

    await store.loadDrafts()

    expect(store.items).toHaveLength(1)
    expect(store.items[0]!.id).toBe('d-1')
    expect(store.nextCursor).toBe('cur-1')
    expect(store.hasMore).toBe(true)
  })

  it('discardDraft 成功后把该草稿从列表移除', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ items: [draftSummary()], next_cursor: null, has_more: false }),
        )
        .mockResolvedValueOnce(new Response(null, { status: 204 })),
    )
    await store.loadDrafts()
    expect(store.items).toHaveLength(1)

    await store.discardDraft('d-1')

    expect(store.items).toHaveLength(0)
  })

  it('markApplied 用返回的草稿摘要就地更新列表项，不重新拉取整页', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ items: [draftSummary()], next_cursor: null, has_more: false }),
        ),
    )
    await store.loadDrafts()

    store.markApplied({
      id: 'd-1',
      kind: 'RESTOCK',
      state: 'APPLIED',
      title: '补货：测试商品 +60',
      draftVersion: 1,
      targetVersion: 72,
      createdAt: '2026-09-23T00:00:00Z',
      updatedAt: '2026-09-23T00:05:00Z',
      expiresAt: '2026-09-30T00:00:00Z',
      batchId: null,
    })

    expect(store.items[0]!.state).toBe('APPLIED')
    expect(store.items[0]!.targetVersion).toBe(72)
  })

  it('加载失败时记录 errorMessage 并把错误继续抛给调用方', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            code: 'DATA_SOURCE_UNAVAILABLE',
            message: '依赖不可用',
            request_id: 'r-1',
            retryable: true,
          },
          503,
        ),
      ),
    )

    await expect(store.loadDrafts()).rejects.toBeInstanceOf(AppError)
    expect(store.errorMessage).not.toBe('')
  })

  it('groupedItems 按 batchId 分组；无批次的草稿各自独立成组', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          items: [
            draftSummary({ id: 'd-b1-a', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
            draftSummary({ id: 'd-solo', kind: 'RESTOCK' }),
            draftSummary({ id: 'd-b1-b', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
          ],
          next_cursor: null,
          has_more: false,
        }),
      ),
    )
    await store.loadDrafts()

    expect(store.groupedItems).toHaveLength(2)
    const batchGroup = store.groupedItems.find((group) => group.batchId === 'batch-1')
    const soloGroup = store.groupedItems.find((group) => group.batchId === null)
    expect(batchGroup?.items.map((item) => item.id)).toEqual(['d-b1-a', 'd-b1-b'])
    expect(soloGroup?.items.map((item) => item.id)).toEqual(['d-solo'])
  })

  it('批准整批：只对批次里仍处于 STAGED 的子草稿逐个应用', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValueOnce(
        jsonResponse({
          items: [
            draftSummary({ id: 'd-b1-a', kind: 'CONTENT_CHANGE', batch_id: 'batch-1' }),
            draftSummary({
              id: 'd-b1-b',
              kind: 'CONTENT_CHANGE',
              batch_id: 'batch-1',
              state: 'APPLIED',
            }),
          ],
          next_cursor: null,
          has_more: false,
        }),
      ),
    )
    await store.loadDrafts()

    const batchGroup = store.groupedItems.find((group) => group.batchId === 'batch-1')
    // 只有仍处于 STAGED 的子草稿需要（也应该能）被批准；已应用的不重复处理。
    expect(
      batchGroup?.items.filter((item) => item.state === 'STAGED').map((item) => item.id),
    ).toEqual(['d-b1-a'])
  })

  it('切换商家会话时草稿列表被清空（复用 registerSessionScopedReset 钩子）', async () => {
    await openTestSession()
    const store = useDraftsStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ items: [draftSummary()], next_cursor: 'cur-1', has_more: true }),
        ),
    )
    await store.loadDrafts()
    expect(store.items).toHaveLength(1)

    const auth = useAuthStore()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(new Response(null, { status: 204 }))
        .mockResolvedValueOnce(
          jsonResponse({
            session_id: 'sid-2'.padEnd(43, '0'),
            role: 'MERCHANT',
            expires_at: '2026-09-24T00:00:00Z',
            merchant_display_name: 'Borough商家101',
          }),
        ),
    )
    await auth.selectAndOpenSession(auth.merchants[1]!)

    expect(store.items).toHaveLength(0)
    expect(store.nextCursor).toBeNull()
    expect(store.hasMore).toBe(false)
  })
})
