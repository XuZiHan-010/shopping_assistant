import { describe, expect, it } from 'vitest'
import { resolveLocale } from './locale'
import { toolDisplayName } from './toolNames'
describe('locale', () => {
  it('cookie 严格验证，按语言权重回退', () => {
    expect(resolveLocale('en-US', 'zh-CN')).toBe('en-US')
    for (const cookie of ['fr', '', 'en-US;drop']) expect(resolveLocale(cookie, 'en-US')).toBe('en-US')
    expect(resolveLocale(undefined, 'en;q=0.2,zh-CN;q=0.9')).toBe('zh-CN')
    expect(resolveLocale(undefined, 'fr')).toBe('zh-CN')
  })
  it('工具显示名与未知工具回退', () => {
    expect(toolDisplayName('search_products', 'zh-CN')).toBe('搜索商品')
    expect(toolDisplayName('unknown_tool', 'zh-CN')).toBe('unknown_tool')
  })
})
