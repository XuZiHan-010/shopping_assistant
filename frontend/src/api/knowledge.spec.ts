import { afterEach, describe, expect, it } from 'vitest'

import {
  createBusinessDomain,
  createKnowledgeDocument,
  deleteBusinessDomain,
  deleteKnowledgeDocument,
  getKnowledgeDocument,
  renameBusinessDomain,
  updateKnowledgeDocument,
} from './knowledge'
import { setChatTransport, type TransportRequest } from './transport'

afterEach(() => {
  setChatTransport(undefined)
})

describe('知识库文档版本感知读写（Task 8/11）', () => {
  it('读取时携带 content_locale 查询参数，返回内容语言与译文状态', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        path: 'index/a.md',
        content: 'English content',
        read_only: false,
        version: '1',
        content_locale: 'en-US',
        translation_status: 'CURRENT',
      })
    })

    const document = await getKnowledgeDocument('index/a.md', new AbortController().signal, {
      contentLocale: 'en-US',
    })

    expect(requests[0]?.path).toBe('/api/admin/knowledge/documents/index/a.md?content_locale=en-US')
    expect(document.contentLocale).toBe('en-US')
    expect(document.translationStatus).toBe('CURRENT')
  })

  it('未指定 contentLocale 时不附加查询参数，行为与引入前一致', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        path: 'index/a.md',
        content: '正文',
        read_only: false,
        version: '1',
        content_locale: 'zh-CN',
        translation_status: 'SOURCE',
      })
    })

    await getKnowledgeDocument('index/a.md', new AbortController().signal)

    expect(requests[0]?.path).toBe('/api/admin/knowledge/documents/index/a.md')
  })

  it('默认更新源版本：is_source_version 为 true，content_locale 为 null', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        path: 'index/a.md',
        content: '新正文',
        read_only: false,
        version: '2',
        content_locale: 'zh-CN',
        translation_status: 'SOURCE',
      })
    })

    await updateKnowledgeDocument('index/a.md', '新正文', '"1"', new AbortController().signal)

    expect(requests[0]).toMatchObject({
      method: 'PUT',
      body: { content: '新正文', is_source_version: true, content_locale: null },
      headers: { 'If-Match': '"1"' },
    })
  })

  it('显式保存译文：is_source_version 为 false，携带目标 content_locale', async () => {
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        path: 'index/a.md',
        content: 'English translation',
        read_only: false,
        version: '1',
        content_locale: 'en-US',
        translation_status: 'CURRENT',
      })
    })

    const document = await updateKnowledgeDocument(
      'index/a.md',
      'English translation',
      '"1"',
      new AbortController().signal,
      { isSourceVersion: false, contentLocale: 'en-US' },
    )

    expect(requests[0]).toMatchObject({
      method: 'PUT',
      body: { content: 'English translation', is_source_version: false, content_locale: 'en-US' },
    })
    expect(document.contentLocale).toBe('en-US')
    expect(document.translationStatus).toBe('CURRENT')
  })
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
      contentLocale: 'und',
      translationStatus: 'SOURCE',
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
