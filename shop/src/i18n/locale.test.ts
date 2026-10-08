import { describe, expect, it } from 'vitest'
import { resolveLocale } from './locale'
import { toolDisplayName } from './toolNames'
describe('locale', () => {
  it('首访默认中文，只有偏好 cookie 的受支持取值能切到英文', () => {
    expect(resolveLocale(undefined)).toBe('zh-CN')
    expect(resolveLocale('zh-CN')).toBe('zh-CN')
    expect(resolveLocale('en-US')).toBe('en-US')
    for (const cookie of ['fr', '', 'en', 'en-US;drop']) expect(resolveLocale(cookie)).toBe('zh-CN')
  })
  it('工具显示名与未知工具回退', () => {
    expect(toolDisplayName('search_products', 'zh-CN')).toBe('搜索商品')
    expect(toolDisplayName('unknown_tool', 'zh-CN')).toBe('unknown_tool')
  })
})
