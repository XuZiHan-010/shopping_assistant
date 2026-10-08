import { describe, expect, it } from 'vitest'
import { categoryLabel, categoryTone } from './categories'

describe('商品类目词表', () => {
  it('中文原样显示，英文查固定词表，未登记的类目原样显示', () => {
    expect(categoryLabel('鞋靴', 'zh-CN')).toBe('鞋靴')
    expect(categoryLabel('鞋靴', 'en-US')).toBe('Shoes')
    expect(categoryLabel('美妆', 'en-US')).toBe('Beauty')
    expect(categoryLabel('测试类目', 'en-US')).toBe('测试类目')
  })

  it('五个演示类目各有占位色调，未登记类目不上色', () => {
    expect(['女装', '男装', '鞋靴', '家居', '美妆'].map(categoryTone)).toEqual(['dress', 'shirt', 'boot', 'home', 'beauty'])
    expect(categoryTone('测试类目')).toBeUndefined()
    expect(categoryTone(undefined)).toBeUndefined()
  })
})
