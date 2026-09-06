import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setChatTransport, type TransportRequest } from '@/api/transport'

import { useKnowledgeStore } from './knowledge'
import { useLocaleStore } from './locale'

/** 手动控制 settle 时机的 Promise，用来构造"谁先谁后返回"的确定性竞态。 */
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function documentResponse(content: string, locale: 'zh-CN' | 'en-US'): Response {
  return Response.json({
    path: 'index/a.md',
    content,
    read_only: false,
    version: '1',
    content_locale: locale,
    translation_status: locale === 'en-US' ? 'CURRENT' : 'SOURCE',
  })
}

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
    store.selectedDocument = { path: 'index/a.md', content: '正文', readOnly: false, version: 'fresh-v2' }

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

describe('知识文档：内容语言与版本感知读写（Task 8/11）', () => {
  it('选中文档时按当前展示语言请求 content_locale', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    const localeStore = useLocaleStore()
    localeStore.setLocale('en-US')
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

    await store.selectNode('index/a.md')

    expect(requests[0]?.path).toBe('/api/admin/knowledge/documents/index/a.md?content_locale=en-US')
    expect(store.selectedDocument?.contentLocale).toBe('en-US')
    expect(store.selectedDocument?.translationStatus).toBe('CURRENT')
  })

  it('saveDocument 把 isSourceVersion/contentLocale 原样透传给 API，不做任何 locale 比较推断', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    store.selectedDocument = {
      path: 'index/a.md',
      content: '原文',
      readOnly: false,
      version: 'v1',
      contentLocale: 'zh-CN',
      translationStatus: 'SOURCE',
    }
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        path: 'index/a.md',
        content: 'English translation',
        read_only: false,
        version: 'v1',
        content_locale: 'en-US',
        translation_status: 'CURRENT',
      })
    })

    await store.saveDocument('English translation', { 'If-Match': '"v1"' }, {
      isSourceVersion: false,
      contentLocale: 'en-US',
    })

    expect(requests[0]?.body).toEqual({
      content: 'English translation',
      is_source_version: false,
      content_locale: 'en-US',
    })
    expect(store.selectedDocument?.translationStatus).toBe('CURRENT')
  })

  it('saveDocument 不传 options 时默认更新源版本，行为与该参数引入前一致', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    store.selectedDocument = {
      path: 'index/a.md',
      content: '原文',
      readOnly: false,
      version: 'v1',
      contentLocale: 'zh-CN',
      translationStatus: 'SOURCE',
    }
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({
        path: 'index/a.md',
        content: '新正文',
        read_only: false,
        version: 'v2',
        content_locale: 'zh-CN',
        translation_status: 'SOURCE',
      })
    })

    await store.saveDocument('新正文', { 'If-Match': '"v1"' })

    expect(requests[0]?.body).toEqual({
      content: '新正文',
      is_source_version: true,
      content_locale: null,
    })
  })
})

describe('语言切换：重新加载当前选中文档（Task 11 Step 6）', () => {
  it('切换语言且当前选中一份文档时，按新语言重新拉一次', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    const localeStore = useLocaleStore()
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      const locale = localeStore.locale
      return Response.json({
        path: 'index/a.md',
        content: locale === 'en-US' ? 'English content' : '中文正文',
        read_only: false,
        version: '1',
        content_locale: locale,
        translation_status: locale === 'en-US' ? 'CURRENT' : 'SOURCE',
      })
    })

    await store.selectNode('index/a.md')
    expect(store.selectedDocument?.content).toBe('中文正文')

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.selectedDocument?.content).toBe('English content')
    expect(requests.some((r) => r.path.includes('content_locale=en-US'))).toBe(true)
  })

  it('未选中文档（或选中的是目录）时，切换语言不发请求', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    const localeStore = useLocaleStore()
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({ roots: [] })
    })

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(requests).toEqual([])
  })

  it('未登录时切换语言不发请求', async () => {
    const store = useKnowledgeStore()
    expect(store.adminToken).toBe('')
    const localeStore = useLocaleStore()
    const requests: TransportRequest[] = []
    setChatTransport(async (request) => {
      requests.push(request)
      throw new Error('不应发起请求')
    })

    localeStore.setLocale('en-US')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(requests).toEqual([])
  })
})

describe('语言切换：epoch 竞态防护（Task 11 Step 6 补齐到 knowledge.ts）', () => {
  it('先发起的一次刷新响应晚到（旧语言内容），不会覆盖后发生的那次已经写入的正确语言内容（真实乱序，epoch 防护）', async () => {
    const store = useKnowledgeStore()
    store.setAdminToken('admin-token')
    const localeStore = useLocaleStore()

    // 先正常选中一次文档（中文），拿到一份已加载的 selectedDocument。
    setChatTransport(async () => documentResponse('中文正文', 'zh-CN'))
    await store.selectNode('index/a.md')
    expect(store.selectedDocument?.content).toBe('中文正文')

    const first = deferred<Response>()
    const second = deferred<Response>()
    let callCount = 0
    setChatTransport(async () => {
      callCount += 1
      return callCount === 1 ? first.promise : second.promise
    })

    // 模拟"第一次刷新还没回来，语言又被切了一次"：手动调用一次
    // reloadForLocale（不经过 watch，代表任意一次仍在途的刷新，epoch 变成
    // 1，发出第一次请求），再切语言触发 watch 里的第二次 reloadForLocale
    // （epoch 再 +1，发出第二次请求）。
    const staleReload = store.reloadForLocale()
    localeStore.setLocale('en-US')

    // 后发起的（较新 epoch、真正对应当前展示语言）请求先回来。
    second.resolve(documentResponse('English content (current)', 'en-US'))
    await vi.waitFor(() => expect(store.selectedDocument?.content).toBe('English content (current)'))

    // 先发起的（较旧 epoch）请求后回来——必须被丢弃。修复前，这会把刚写好的
    // 正确内容覆盖成一份过期的、语言不对的正文；管理员如果没注意到就直接
    // 保存（默认 isSourceVersion: true），会把源文档本身覆盖成错误语言的
    // 内容——不只是一次 UI 展示错误，是一次真实的数据损坏。这里断言
    // selectedDocument 不会倒退，从根上堵住了这条数据损坏路径。
    first.resolve(documentResponse('过期的中文内容', 'zh-CN'))
    await staleReload
    // 给一次事件循环，确认"迟到的响应"确实被处理过（而不是还没跑到那一行）。
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(store.selectedDocument?.content).toBe('English content (current)')
    expect(store.selectedDocument?.contentLocale).toBe('en-US')
  })
})
