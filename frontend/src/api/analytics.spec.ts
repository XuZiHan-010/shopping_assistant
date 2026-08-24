import { afterEach, describe, expect, it } from 'vitest'

import { getChatBiCategories, getChatBiOverview, triggerChatBiRollup } from './analytics'
import { setChatTransport, type TransportRequest } from './transport'

afterEach(() => {
  setChatTransport(undefined)
})

describe('Chat BI 管理员 API', () => {
  it('以管理员鉴权读取总览与分类，并将窗口编码进查询参数', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      if (request.path.includes('/overview')) {
        return Response.json({
          start_date: '2026-08-17',
          end_date: '2026-08-23',
          answer_total: 2,
          business_question_total: 1,
          feedback_total: 1,
          thinking_sample_count: 2,
          adoption_rate: 0.5,
          user_accuracy_rate: null,
          system_accuracy_rate: 1,
          avg_thinking_ms: 1200,
          hit_rate: 1,
          failure_rate: 0,
          daily: [],
        })
      }
      return Response.json({
        start_date: '2026-08-17',
        end_date: '2026-08-23',
        items: [],
      })
    })

    const window = { startDate: '2026-08-17', endDate: '2026-08-23' }
    const [overview, categories] = await Promise.all([
      getChatBiOverview(window, new AbortController().signal),
      getChatBiCategories(window, new AbortController().signal),
    ])

    expect(overview.metrics.adoptionRate).toBe(0.5)
    expect(categories).toEqual([])
    expect(requests).toEqual([
      expect.objectContaining({
        path: '/api/admin/analytics/chatbi/overview?start_date=2026-08-17&end_date=2026-08-23',
        method: 'GET',
        auth: 'admin',
      }),
      expect.objectContaining({
        path: '/api/admin/analytics/chatbi/categories?start_date=2026-08-17&end_date=2026-08-23',
        method: 'GET',
        auth: 'admin',
      }),
    ])
  })

  it('以 JSON 请求体触发指定窗口的幂等汇总刷新', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        start_date: '2026-08-17',
        end_date: '2026-08-23',
        rows_written: 12,
      })
    })

    const rowsWritten = await triggerChatBiRollup(
      { startDate: '2026-08-17', endDate: '2026-08-23' },
      new AbortController().signal,
    )

    expect(rowsWritten).toBe(12)
    expect(requests).toEqual([
      {
        path: '/api/admin/analytics/chatbi/rollup',
        method: 'POST',
        auth: 'admin',
        body: { start_date: '2026-08-17', end_date: '2026-08-23' },
      },
    ])
  })
})
