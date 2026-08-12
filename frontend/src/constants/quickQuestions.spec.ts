import { describe, expect, it } from 'vitest'

import { matchScenario } from '@/api/mock/scenarios'

import { QUICK_QUESTIONS } from './quickQuestions'

describe('QUICK_QUESTIONS', () => {
  it('每个快速问题都命中专属 fixture，而不是闲聊兜底', () => {
    for (const { question } of QUICK_QUESTIONS) {
      expect(matchScenario(question)).not.toBe('chatGreeting')
    }
  })
})
