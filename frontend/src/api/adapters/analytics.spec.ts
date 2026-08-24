import { describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'

import { toChatBiCategories, toChatBiOverview } from './analytics'

describe('Chat BI 契约 Adapter', () => {
  it('将总览、日趋势和六项指标完整映射为前端模型', () => {
    const raw = {
      start_date: '2026-08-17',
      end_date: '2026-08-23',
      answer_total: 20,
      business_question_total: 16,
      feedback_total: 4,
      thinking_sample_count: 18,
      adoption_rate: 0.4,
      user_accuracy_rate: null,
      system_accuracy_rate: 0.8,
      avg_thinking_ms: 2500,
      hit_rate: 0.75,
      failure_rate: 0.05,
      daily: [
        {
          stat_date: '2026-08-23',
          answer_total: 4,
          adoption_rate: null,
          user_accuracy_rate: 1,
          system_accuracy_rate: 0.75,
          avg_thinking_ms: null,
          hit_rate: 1,
          failure_rate: 0,
        },
      ],
    } as components['schemas']['ChatBiOverviewResponse']

    expect(toChatBiOverview(raw)).toEqual({
      startDate: '2026-08-17',
      endDate: '2026-08-23',
      answerTotal: 20,
      businessQuestionTotal: 16,
      feedbackTotal: 4,
      thinkingSampleCount: 18,
      metrics: {
        adoptionRate: 0.4,
        userAccuracyRate: null,
        systemAccuracyRate: 0.8,
        avgThinkingMs: 2500,
        hitRate: 0.75,
        failureRate: 0.05,
      },
      daily: [
        {
          statDate: '2026-08-23',
          answerTotal: 4,
          metrics: {
            adoptionRate: null,
            userAccuracyRate: 1,
            systemAccuracyRate: 0.75,
            avgThinkingMs: null,
            hitRate: 1,
            failureRate: 0,
          },
        },
      ],
    })
  })

  it('将分类的中文展示名和空指标保持到领域模型', () => {
    const raw = {
      items: [
        {
          category: 'TRADE',
          category_display_name: '交易分析',
          answer_total: 8,
          adoption_rate: null,
          user_accuracy_rate: null,
          system_accuracy_rate: 0.9,
          avg_thinking_ms: 1900,
          hit_rate: 0.75,
          failure_rate: 0,
        },
      ],
    } as components['schemas']['ChatBiCategoriesResponse']

    expect(toChatBiCategories(raw)).toEqual([
      {
        category: 'TRADE',
        displayName: '交易分析',
        answerTotal: 8,
        metrics: {
          adoptionRate: null,
          userAccuracyRate: null,
          systemAccuracyRate: 0.9,
          avgThinkingMs: 1900,
          hitRate: 0.75,
          failureRate: 0,
        },
      },
    ])
  })
})
