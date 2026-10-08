import { describe, expect, it, vi, afterEach } from 'vitest'
import { loadPreferences } from './preferences'
afterEach(() => { vi.restoreAllMocks(); localStorage.clear() })
describe('preferences', () => {
  it('存储受限时使用默认值', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('blocked') })
    expect(loadPreferences()).toEqual({ theme: 'system', size: 'md' })
  })
  it('拒绝非法值', () => {
    localStorage.setItem('borough-shop-prefs', JSON.stringify({ theme: 'bad', size: 'huge' }))
    expect(loadPreferences()).toEqual({ theme: 'system', size: 'md' })
  })
})
