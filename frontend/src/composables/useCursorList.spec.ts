/**
 * 游标列表状态机（W Task 9 fix round 1）：订单页与商品页共用。
 *
 * 契约 §8.7.4：游标绑定查询形状（筛选、语言、limit、会话主体）且 24 小时过期；
 * 拿失效游标得到 `INVALID_CURSOR` 时必须从第一页重读（第 5 条），不能重试旧游标。
 */
import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { AppError } from '@/api/errors'
import { deferred } from '@/testing/workspacePayloads'

import { useCursorList, type CursorPage } from './useCursorList'

function pageOf(items: string[], nextCursor: string | null = null): CursorPage<string> {
  return { items, nextCursor, hasMore: nextCursor !== null }
}

function invalidCursor(): AppError {
  return new AppError('INVALID_CURSOR', '游标失效', { status: 422 })
}

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) await Promise.resolve()
}

describe('useCursorList', () => {
  it('reload 不带游标请求第一页，写入条目与是否还有更多', async () => {
    const fetchPage = vi.fn(async () => pageOf(['a', 'b'], 'c1'))
    const list = useCursorList(fetchPage)
    expect(list.status.value).toBe('loading')

    await list.reload()

    expect(fetchPage).toHaveBeenCalledWith(null)
    expect(list.items.value).toEqual(['a', 'b'])
    expect(list.status.value).toBe('ready')
    expect(list.hasMore.value).toBe(true)
  })

  it('loadMore 带上游标并追加；没有下一页后不再请求', async () => {
    const fetchPage = vi.fn(async (cursor: string | null) =>
      cursor === 'c1' ? pageOf(['c']) : pageOf(['a', 'b'], 'c1'),
    )
    const list = useCursorList(fetchPage)
    await list.reload()
    await list.loadMore()

    expect(fetchPage).toHaveBeenLastCalledWith('c1')
    expect(list.items.value).toEqual(['a', 'b', 'c'])
    expect(list.hasMore.value).toBe(false)

    await list.loadMore()
    expect(fetchPage).toHaveBeenCalledTimes(2)
  })

  it('先发的慢 reload 晚到时被丢弃', async () => {
    const slow = deferred<CursorPage<string>>()
    let calls = 0
    const list = useCursorList(async () => {
      calls += 1
      return calls === 1 ? slow.promise : pageOf(['new'])
    })
    const first = list.reload()
    await list.reload()
    slow.resolve(pageOf(['old']))
    await first

    expect(list.items.value).toEqual(['new'])
  })

  it('loadMore 未返回时 reload：旧的下一页不会追加到新列表', async () => {
    const slowMore = deferred<CursorPage<string>>()
    let firstPages = 0
    const list = useCursorList(async (cursor) => {
      if (cursor) return slowMore.promise
      firstPages += 1
      return pageOf([`first-${firstPages}`], 'c1')
    })
    await list.reload()
    const more = list.loadMore()
    await list.reload()
    slowMore.resolve(pageOf(['stale']))
    await more

    expect(list.items.value).toEqual(['first-2'])
    expect(list.moreStatus.value).toBe('idle')
  })

  it('loadMore 遇到 INVALID_CURSOR：从第一页重读、替换条目并标记 restarted；下一次 reload 清除标记', async () => {
    const fetchPage = vi.fn(async (cursor: string | null) => {
      if (cursor) throw invalidCursor()
      return pageOf(['a'], 'c1')
    })
    const list = useCursorList(fetchPage)
    await list.reload()
    await list.loadMore()
    await settle()

    expect(fetchPage).toHaveBeenLastCalledWith(null)
    expect(list.items.value).toEqual(['a'])
    expect(list.status.value).toBe('ready')
    expect(list.moreStatus.value).toBe('idle')
    expect(list.restarted.value).toBe(true)

    await list.reload()
    expect(list.restarted.value).toBe(false)
  })

  it('loadMore 其他失败：保留条目、标记错误，再试沿用同一游标', async () => {
    let fail = true
    const fetchPage = vi.fn(async (cursor: string | null) => {
      if (!cursor) return pageOf(['a'], 'c1')
      if (fail) throw new AppError('DATA_SOURCE_UNAVAILABLE', '暂不可用', { status: 503 })
      return pageOf(['b'])
    })
    const list = useCursorList(fetchPage)
    await list.reload()
    await list.loadMore()
    expect(list.items.value).toEqual(['a'])
    expect(list.moreStatus.value).toBe('error')

    fail = false
    await list.loadMore()
    expect(fetchPage).toHaveBeenLastCalledWith('c1')
    expect(list.items.value).toEqual(['a', 'b'])
    expect(list.moreStatus.value).toBe('idle')
  })

  it('第一页失败标记 error', async () => {
    const list = useCursorList(async () => {
      throw new AppError('DATA_SOURCE_UNAVAILABLE', '暂不可用', { status: 503 })
    })
    await list.reload()
    expect(list.status.value).toBe('error')
  })

  it('所在作用域销毁后，晚到的响应被丢弃', async () => {
    const slow = deferred<CursorPage<string>>()
    const scope = effectScope()
    const list = scope.run(() => useCursorList(() => slow.promise))!
    const pending = list.reload()
    scope.stop()
    slow.resolve(pageOf(['late']))
    await pending

    expect(list.items.value).toEqual([])
    expect(list.status.value).toBe('loading')
  })
})
