import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useKnowledgeStore } from './knowledge'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})

describe('知识库后台令牌', () => {
  it('令牌不写入 localStorage', () => {
    const store = useKnowledgeStore()
    store.setAdminToken('secret-token')

    expect(localStorage.getItem('adminToken')).toBeNull()
    expect(JSON.stringify(localStorage)).not.toContain('secret-token')
  })

  it('令牌走 X-Admin-Token 而不是 Authorization', () => {
    const store = useKnowledgeStore()
    store.setAdminToken('secret-token')

    const headers = store.adminHeaders()

    expect(headers['X-Admin-Token']).toBe('secret-token')
    expect(headers.Authorization).toBeUndefined()
  })

  it('未授权时不发起任何请求', async () => {
    const store = useKnowledgeStore()

    await expect(store.loadTree()).rejects.toThrow(/未授权/)
  })

  it('登出清空令牌与树', () => {
    const store = useKnowledgeStore()
    store.setAdminToken('secret-token')
    store.roots = [
      {
        name: 'index',
        path: 'index',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'v1',
        children: [],
      },
    ]
    store.signOut()

    expect(store.adminToken).toBe('')
    expect(store.roots).toEqual([])
  })
})
