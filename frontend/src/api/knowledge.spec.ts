import { afterEach, describe, expect, it } from 'vitest'

import {
  createBusinessDomain,
  createKnowledgeDocument,
  deleteBusinessDomain,
  deleteKnowledgeDocument,
  renameBusinessDomain,
} from './knowledge'
import { setChatTransport, type TransportRequest } from './transport'

afterEach(() => {
  setChatTransport(undefined)
})

describe('知识库后台写操作 API', () => {
  it('新建文档以管理员鉴权 POST 到 /documents', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json(
        { path: 'index/新文档.md', content: '内容', read_only: false, version: '1' },
        { status: 201 },
      )
    })

    const document = await createKnowledgeDocument(
      'index/新文档.md',
      '内容',
      new AbortController().signal,
    )

    expect(document).toEqual({
      path: 'index/新文档.md',
      content: '内容',
      readOnly: false,
      version: '1',
    })
    expect(requests).toEqual([
      expect.objectContaining({
        path: '/api/admin/knowledge/documents',
        method: 'POST',
        body: { path: 'index/新文档.md', content: '内容' },
        auth: 'admin',
      }),
    ])
  })

  it('删除文档携带编码后的路径与 If-Match', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return new Response(null, { status: 204 })
    })

    await deleteKnowledgeDocument('index/运营手册.md', '"1"', new AbortController().signal)

    expect(requests).toEqual([
      expect.objectContaining({
        path: '/api/admin/knowledge/documents/index/%E8%BF%90%E8%90%A5%E6%89%8B%E5%86%8C.md',
        method: 'DELETE',
        headers: { 'If-Match': '"1"' },
        auth: 'admin',
      }),
    ])
  })

  it('新建业务域 POST name 到 /business-domains', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json(
        {
          name: '客服',
          path: '业务/客服',
          node_type: 'directory',
          read_only: false,
          size: 0,
          version: 'v1',
          children: [],
        },
        { status: 201 },
      )
    })

    const domain = await createBusinessDomain('客服', new AbortController().signal)

    expect(domain.path).toBe('业务/客服')
    expect(requests).toEqual([
      expect.objectContaining({
        path: '/api/admin/knowledge/business-domains',
        method: 'POST',
        body: { name: '客服' },
        auth: 'admin',
      }),
    ])
  })

  it('重命名业务域将当前名称编码进查询参数，新名称放进请求体', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        name: '售后',
        path: '业务/售后',
        node_type: 'directory',
        read_only: false,
        size: 0,
        version: 'v2',
        children: [],
      })
    })

    await renameBusinessDomain('客服', '售后', '"v1"', new AbortController().signal)

    expect(requests).toEqual([
      expect.objectContaining({
        path: '/api/admin/knowledge/business-domains?name=%E5%AE%A2%E6%9C%8D',
        method: 'PUT',
        body: { new_name: '售后' },
        headers: { 'If-Match': '"v1"' },
        auth: 'admin',
      }),
    ])
  })

  it('删除业务域固定携带 recursive=true 与 If-Match', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return new Response(null, { status: 204 })
    })

    await deleteBusinessDomain('客服', '"v1"', new AbortController().signal)

    expect(requests).toEqual([
      expect.objectContaining({
        path: '/api/admin/knowledge/business-domains?name=%E5%AE%A2%E6%9C%8D&recursive=true',
        method: 'DELETE',
        headers: { 'If-Match': '"v1"' },
        auth: 'admin',
      }),
    ])
  })
})
