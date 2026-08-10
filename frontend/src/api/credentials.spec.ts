import { afterEach, describe, expect, it } from 'vitest'

import { buildAuthHeaders, setCredentialProvider } from './credentials'

describe('buildAuthHeaders', () => {
  afterEach(() => {
    // 防止某条用例注册的 provider 泄漏到下一条，让断言依赖执行顺序。
    setCredentialProvider(undefined)
  })

  it('merchant 通道只发 Authorization', () => {
    setCredentialProvider(() => ({ merchantToken: 'demo-token-100', adminToken: 'admin-secret' }))
    const headers = buildAuthHeaders('merchant')
    expect(headers.Authorization).toBe('Bearer demo-token-100')
    expect(headers['X-Admin-Token']).toBeUndefined()
  })

  it('admin 通道只发 X-Admin-Token，绝不发 Authorization', () => {
    setCredentialProvider(() => ({ merchantToken: 'demo-token-100', adminToken: 'admin-secret' }))
    const headers = buildAuthHeaders('admin')
    expect(headers['X-Admin-Token']).toBe('admin-secret')
    expect(headers.Authorization).toBeUndefined()
  })

  it('none 通道不发任何凭证', () => {
    expect(buildAuthHeaders('none')).toEqual({})
  })

  it('缺凭证时快速失败，不发出注定 401 的请求', () => {
    setCredentialProvider(() => ({}))
    expect(() => buildAuthHeaders('merchant')).toThrow(
      expect.objectContaining({ code: 'AUTH_REQUIRED' }),
    )
  })

  it('抛出的错误不泄漏 token 明文', () => {
    setCredentialProvider(() => ({ merchantToken: undefined, adminToken: 'admin-secret' }))
    try {
      buildAuthHeaders('merchant')
      expect.unreachable('应抛出 AUTH_REQUIRED')
    } catch (error) {
      expect((error as Error).message).not.toContain('admin-secret')
    }
  })

  it('未注册 provider 时视为无凭证，快速失败', () => {
    expect(() => buildAuthHeaders('admin')).toThrow(
      expect.objectContaining({ code: 'AUTH_REQUIRED' }),
    )
  })
})
