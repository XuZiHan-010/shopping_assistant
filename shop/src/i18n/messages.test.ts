import { describe, expect, it } from 'vitest'
import { messages, pluralKey } from './messages'

describe('双语字典', () => {
  it('履约事件标签只转述事件类型，不添加后端没有的物流细节（R7）', () => {
    for (const locale of ['zh-CN', 'en-US'] as const) {
      const labels = Object.entries(messages[locale]).filter(([key]) => key.startsWith('ev.')).map(([, value]) => value)
      expect(labels.join('|')).not.toMatch(/转运中心|快递员|sorting centre|courier/)
    }
    expect(messages['zh-CN']['ev.IN_TRANSIT']).toBe('运输中')
    expect(messages['en-US']['ev.OUT_FOR_DELIVERY']).toBe('Out for delivery')
  })

  it('英文单数使用 .one 变体，其余数量与中文使用原键', () => {
    expect(pluralKey('en-US', 'home.orderCount', 1)).toBe('home.orderCount.one')
    expect(pluralKey('en-US', 'home.orderCount', 2)).toBe('home.orderCount')
    expect(pluralKey('en-US', 'home.orderCount', 0)).toBe('home.orderCount')
    expect(pluralKey('zh-CN', 'items', 1)).toBe('items')
  })
})
