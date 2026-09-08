import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { setChatTransport, type TransportRequest } from '@/api/transport'

import { useKnowledgeStore } from './knowledge'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  sessionStorage.clear()
})

afterEach(() => {
  setChatTransport(undefined)
})

const EMPTY_TREE_RESPONSE = { roots: [] }

function domainNode(name: string, version: string) {
  return {
    name,
    path: `业务/${name}`,
    node_type: 'directory' as const,
    read_only: false,
    size: 0,
    version,
    children: [],
  }
}

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

describe('知识库后台节点选中', () => {
  it('选中目录路径只更新选中项，不加载文档内容', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')

    await store.selectNode('业务/客服')

    expect(store.selectedPath).toBe('业务/客服')
    expect(store.selectedDocument).toBeUndefined()
  })

  it('选中文档路径会加载文档内容', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    setChatTransport(async () =>
      Response.json({ path: 'index/a.md', content: '正文', read_only: false, version: '1' }),
    )

    await store.selectNode('index/a.md')

    expect(store.selectedPath).toBe('index/a.md')
    expect(store.selectedDocument?.content).toBe('正文')
  })
})

describe('知识库后台新建与删除', () => {
  it('新建文档成功后刷新目录树并选中新文档', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      if (request.method === 'POST') {
        return Response.json(
          { path: 'index/新文档.md', content: '内容', read_only: false, version: '1' },
          { status: 201 },
        )
      }
      return Response.json(EMPTY_TREE_RESPONSE)
    })

    await store.createDocument('index/新文档.md', '内容')

    expect(store.selectedPath).toBe('index/新文档.md')
    expect(store.selectedDocument?.content).toBe('内容')
    expect(requests.some((request) => request.path === '/api/admin/knowledge/tree')).toBe(true)
  })

  it('新建业务域成功后刷新目录树并选中新业务域', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    setChatTransport(async (request) => {
      if (request.method === 'POST') return Response.json(domainNode('客服', 'v1'), { status: 201 })
      return Response.json(EMPTY_TREE_RESPONSE)
    })

    await store.createDomain('客服')

    expect(store.selectedPath).toBe('业务/客服')
    expect(store.selectedDocument).toBeUndefined()
  })

  it('重命名业务域使用当前选中节点的名称与版本作为 If-Match', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    store.roots = [
      {
        name: '业务',
        path: '业务',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'biz-v1',
        children: [
          {
            name: '客服',
            path: '业务/客服',
            nodeType: 'directory',
            readOnly: false,
            size: 0,
            version: 'domain-v1',
            children: [],
          },
        ],
      },
    ]
    await store.selectNode('业务/客服')

    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      if (request.method === 'PUT') return Response.json(domainNode('售后', 'domain-v2'))
      return Response.json(EMPTY_TREE_RESPONSE)
    })

    await store.renameDomain('售后')

    expect(requests[0]).toEqual(
      expect.objectContaining({
        path: '/api/admin/knowledge/business-domains?name=%E5%AE%A2%E6%9C%8D',
        method: 'PUT',
        body: { new_name: '售后' },
        headers: { 'If-Match': '"domain-v1"' },
      }),
    )
    expect(store.selectedPath).toBe('业务/售后')
  })

  it('删除已加载文档时使用文档最新版本作为 If-Match', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    store.roots = [
      {
        name: 'index',
        path: 'index',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'idx-v1',
        children: [
          {
            name: 'a.md',
            path: 'index/a.md',
            nodeType: 'document',
            readOnly: false,
            size: 1,
            version: 'stale-v1',
            children: [],
          },
        ],
      },
    ]
    store.selectedPath = 'index/a.md'
    store.selectedDocument = {
      path: 'index/a.md',
      content: '正文',
      readOnly: false,
      version: 'fresh-v2',
    }

    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      if (request.method === 'DELETE') return new Response(null, { status: 204 })
      return Response.json(EMPTY_TREE_RESPONSE)
    })

    await store.deleteSelected()

    expect(requests[0]).toEqual(
      expect.objectContaining({
        path: '/api/admin/knowledge/documents/index/a.md',
        method: 'DELETE',
        headers: { 'If-Match': '"fresh-v2"' },
      }),
    )
    expect(store.selectedPath).toBe('')
    expect(store.selectedDocument).toBeUndefined()
  })

  it('删除业务域时固定携带 recursive=true', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    store.roots = [
      {
        name: '业务',
        path: '业务',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'biz-v1',
        children: [
          {
            name: '客服',
            path: '业务/客服',
            nodeType: 'directory',
            readOnly: false,
            size: 0,
            version: 'domain-v1',
            children: [],
          },
        ],
      },
    ]
    store.selectedPath = '业务/客服'

    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      if (request.method === 'DELETE') return new Response(null, { status: 204 })
      return Response.json(EMPTY_TREE_RESPONSE)
    })

    await store.deleteSelected()

    expect(requests[0]).toEqual(
      expect.objectContaining({
        path: '/api/admin/knowledge/business-domains?name=%E5%AE%A2%E6%9C%8D&recursive=true',
        method: 'DELETE',
        headers: { 'If-Match': '"domain-v1"' },
      }),
    )
    expect(store.selectedPath).toBe('')
  })
})
