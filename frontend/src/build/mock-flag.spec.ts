import { describe, expect, it } from 'vitest'

import { assertMockDisabledInProduction } from './mock-flag'

describe('assertMockDisabledInProduction', () => {
  it('生产模式下开启 Mock 必须抛错', () => {
    expect(() => assertMockDisabledInProduction('production', { VITE_USE_MOCK: 'true' })).toThrow(
      /VITE_USE_MOCK/,
    )
  })

  it('生产模式下未开启 Mock 时放行', () => {
    expect(() => assertMockDisabledInProduction('production', {})).not.toThrow()
    expect(() =>
      assertMockDisabledInProduction('production', { VITE_USE_MOCK: 'false' }),
    ).not.toThrow()
  })

  it('开发模式下开启 Mock 是正常用法，不得拦截', () => {
    expect(() =>
      assertMockDisabledInProduction('development', { VITE_USE_MOCK: 'true' }),
    ).not.toThrow()
  })

  it('只认精确的 true，与 transport.ts 的判定保持一致', () => {
    expect(() =>
      assertMockDisabledInProduction('production', { VITE_USE_MOCK: 'TRUE' }),
    ).not.toThrow()
    expect(() => assertMockDisabledInProduction('production', { VITE_USE_MOCK: '1' })).not.toThrow()
  })
})
