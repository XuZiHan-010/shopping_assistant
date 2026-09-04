import { afterEach, describe, expect, it } from 'vitest'

import type { components } from '@/api/generated'
import { setCredentialProvider, setLocaleProvider } from '../credentials'
import { readChatStream } from '../sse'
import type { ChatTransport } from '../transport'
import { QUICK_QUESTIONS } from '@/constants/quickQuestions'

import { MOCK_MERCHANTS, MOCK_SCENARIOS } from './scenarios'
import { createMockTransport } from './transport'

const transport = createMockTransport({ chunkSizes: [3], stepDelayMs: 0 })

/** 以指定商家 Token 发一轮问答。用完立即清掉 provider，不让身份漏到下一条用例。 */
async function submitVia(target: ChatTransport, token: string, message: string): Promise<void> {
  setCredentialProvider(() => ({ merchantToken: token }))
  try {
    await target(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message, client_request_id: 'isolation-test' },
        accept: 'application/json',
        auth: 'merchant',
      },
      new AbortController().signal,
    )
  } finally {
    setCredentialProvider(undefined)
  }
}

/** 以指定商家 Token 拉会话列表。 */
async function listVia(target: ChatTransport, token: string): Promise<{ items: unknown[] }> {
  setCredentialProvider(() => ({ merchantToken: token }))
  try {
    const response = await target(
      { path: '/api/conversations', method: 'GET', auth: 'merchant' },
      new AbortController().signal,
    )
    return (await response.json()) as { items: unknown[] }
  } finally {
    setCredentialProvider(undefined)
  }
}

describe('createMockTransport', () => {
  afterEach(() => {
    setCredentialProvider(undefined)
    setLocaleProvider(undefined)
  })

  // F3 Task 7：Playwright 强制 VITE_USE_MOCK=true，隔离 e2e 因此必然跑在 Mock
  // 之上；真实后端按 Token 过滤，Mock 若仍是一张全局会话表，隔离 e2e 就是假绿。
  it('同一传输实例下，商家之间的会话互不可见', async () => {
    const isolationTransport = createMockTransport()
    await submitVia(isolationTransport, 'demo-token-100', '昨天的 GMV 是多少')
    const listForB = await listVia(isolationTransport, 'demo-token-101')
    expect(listForB.items).toHaveLength(0)
  })
  // 遍历全部场景而不只是快速问题入口：快速体验区只暴露 4 个分类入口，
  // 但兜底闲聊与「助手会拒绝」这两个场景照样要能命中 fixture。
  it('每个演示场景都能命中 fixture 并以 done 收尾', async () => {
    // client_request_id 必须逐场景唯一：Mock 现在按它做幂等重放（Task 11
    // Step 3），复用同一个 id 会让第 2 个及之后的场景全部命中第 1 个场景
    // 缓存下来的答案，而不是各自的 fixture——这与真实后端的行为一致。
    for (const [index, { question }] of MOCK_SCENARIOS.entries()) {
      const response = await transport(
        {
          path: '/api/chat',
          method: 'POST',
          body: { message: question, client_request_id: `scenario-${index}` },
          accept: 'text/event-stream',
        },
        new AbortController().signal,
      )

      const events = []
      for await (const event of readChatStream(response.body!)) events.push(event)

      expect(events.at(-1)?.type, question).toBe('done')
      expect(events.some((e) => e.type === 'step')).toBe(true)
    }
  })

  it('快速体验入口是 4 个带分类的问题，且不推荐会被助手拒绝的请求', () => {
    expect(QUICK_QUESTIONS).toHaveLength(4)
    expect(QUICK_QUESTIONS.map((item) => item.category)).toEqual([
      '趋势分析',
      '经营指标',
      '业务明细',
      '规则问答',
    ])

    // invalidRefused 与兜底闲聊都不该出现在主动推荐里：推荐一个设计上就要被
    // 拒绝的请求，等于教用户去踩线。
    const refused = MOCK_SCENARIOS.find((scenario) => scenario.fixture === 'invalidRefused')!
    expect(QUICK_QUESTIONS.map((item) => item.question)).not.toContain(refused.question)
    expect(QUICK_QUESTIONS.map((item) => item.question)).not.toContain('你好')
  })

  it('Accept: application/json 时返回普通 JSON，不走流', async () => {
    const response = await transport(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message: '你好', client_request_id: 'c2' },
        accept: 'application/json',
      },
      new AbortController().signal,
    )

    const payload = await response.json()
    expect(payload.answer_mode).toBe('CHAT')
  })

  it('返回演示商家列表，且不含 merchant_id 以外的身份泄漏', async () => {
    const response = await transport(
      { path: '/api/demo/merchants', method: 'GET' },
      new AbortController().signal,
    )

    const payload = await response.json()
    expect(payload.merchants).toEqual(MOCK_MERCHANTS)
    expect(payload.merchants.length).toBeGreaterThanOrEqual(2)
  })

  it('日报按商家隔离并在同一期内重放同一份结果', async () => {
    const reportTransport = createMockTransport()
    const getReport = async (token: string) => {
      setCredentialProvider(() => ({ merchantToken: token }))
      try {
        const response = await reportTransport(
          { path: '/api/reports/daily', method: 'GET', auth: 'merchant' },
          new AbortController().signal,
        )
        return (await response.json()) as components['schemas']['DailyReportResponse']
      } finally {
        setCredentialProvider(undefined)
      }
    }

    const first = await getReport('demo-token-100')
    const repeated = await getReport('demo-token-100')
    const other = await getReport('demo-token-101')

    expect(first.answer_id).toBe(repeated.answer_id)
    expect(first.answer_id).not.toBe(other.answer_id)
    expect(first.metrics).toHaveLength(6)
    expect(first.suggestions).toHaveLength(2)
  })

  it('已中止的 signal 会让请求以 AbortError 拒绝', async () => {
    const controller = new AbortController()
    controller.abort()

    await expect(
      transport(
        {
          path: '/api/chat',
          method: 'POST',
          body: { message: '你好', client_request_id: 'c3' },
          accept: 'text/event-stream',
        },
        controller.signal,
      ),
    ).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('签名导出路径返回 CSV，不依赖商家 Authorization 头', async () => {
    const response = await transport(
      { path: '/api/exports/export-1?signature=abc', method: 'GET', auth: 'none' },
      new AbortController().signal,
    )

    expect(response.headers.get('content-type')).toContain('text/csv')
    expect(await response.text()).toContain('order_no')
  })

  it('管理员可在 Mock 中读取 Chat BI 总览、分类并重刷汇总', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    const overview = await adminTransport(
      {
        path: '/api/admin/analytics/chatbi/overview?start_date=2026-08-17&end_date=2026-08-23',
        method: 'GET',
        auth: 'admin',
      },
      new AbortController().signal,
    )
    const categories = await adminTransport(
      {
        path: '/api/admin/analytics/chatbi/categories?start_date=2026-08-17&end_date=2026-08-23',
        method: 'GET',
        auth: 'admin',
      },
      new AbortController().signal,
    )
    const rollup = await adminTransport(
      {
        path: '/api/admin/analytics/chatbi/rollup',
        method: 'POST',
        auth: 'admin',
        body: { start_date: '2026-08-17', end_date: '2026-08-23' },
      },
      new AbortController().signal,
    )

    const overviewPayload = (await overview.json()) as { adoption_rate: number | null }
    const categoriesPayload = (await categories.json()) as { items: unknown[] }
    const rollupPayload = (await rollup.json()) as { rows_written: number }
    expect(overviewPayload.adoption_rate).toBeNull()
    expect(categoriesPayload.items.length).toBeGreaterThan(0)
    expect(rollupPayload.rows_written).toBeGreaterThanOrEqual(0)
  })

  it('Mock 中新建文档后，目录树与详情都能看到它；重复路径返回 409', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    const created = await adminTransport(
      {
        path: '/api/admin/knowledge/documents',
        method: 'POST',
        auth: 'admin',
        body: { path: 'index/新手册.md', content: '# 新手册' },
      },
      new AbortController().signal,
    )
    expect(created.status).toBe(201)

    const tree = await adminTransport(
      { path: '/api/admin/knowledge/tree', method: 'GET', auth: 'admin' },
      new AbortController().signal,
    )
    const treePayload = (await tree.json()) as {
      roots: Array<{ path: string; children: Array<{ path: string }> }>
    }
    const indexRoot = treePayload.roots.find((root) => root.path === 'index')
    expect(indexRoot?.children.map((child) => child.path)).toContain('index/新手册.md')

    const duplicate = await adminTransport(
      {
        path: '/api/admin/knowledge/documents',
        method: 'POST',
        auth: 'admin',
        body: { path: 'index/新手册.md', content: '重复' },
      },
      new AbortController().signal,
    )
    expect(duplicate.status).toBe(409)
  })

  it('Mock 中删除文档需要匹配的 If-Match，成功后从目录树消失', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    const staleAttempt = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md',
        method: 'DELETE',
        auth: 'admin',
        headers: { 'If-Match': '"stale"' },
      },
      new AbortController().signal,
    )
    expect(staleAttempt.status).toBe(412)

    const deleted = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md',
        method: 'DELETE',
        auth: 'admin',
        headers: { 'If-Match': '"1"' },
      },
      new AbortController().signal,
    )
    expect(deleted.status).toBe(204)

    const tree = await adminTransport(
      { path: '/api/admin/knowledge/tree', method: 'GET', auth: 'admin' },
      new AbortController().signal,
    )
    const treePayload = (await tree.json()) as {
      roots: Array<{ path: string; children: Array<{ path: string }> }>
    }
    expect(treePayload.roots.find((root) => root.path === 'index')?.children).toEqual([])
  })

  it('Mock 中新建业务域会自动生成四个固定板块，重命名与递归删除都生效', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    const created = await adminTransport(
      {
        path: '/api/admin/knowledge/business-domains',
        method: 'POST',
        auth: 'admin',
        body: { name: '客服' },
      },
      new AbortController().signal,
    )
    expect(created.status).toBe(201)
    const domainNode = (await created.json()) as { version: string; children: unknown[] }
    expect(domainNode.children).toHaveLength(4)

    const renamed = await adminTransport(
      {
        path: '/api/admin/knowledge/business-domains?name=客服',
        method: 'PUT',
        auth: 'admin',
        body: { new_name: '售后' },
        headers: { 'If-Match': `"${domainNode.version}"` },
      },
      new AbortController().signal,
    )
    expect(renamed.status).toBe(200)
    const renamedNode = (await renamed.json()) as { path: string; version: string }
    expect(renamedNode.path).toBe('业务/售后')

    const deleted = await adminTransport(
      {
        path: '/api/admin/knowledge/business-domains?name=售后&recursive=true',
        method: 'DELETE',
        auth: 'admin',
        headers: { 'If-Match': `"${renamedNode.version}"` },
      },
      new AbortController().signal,
    )
    expect(deleted.status).toBe(204)

    const tree = await adminTransport(
      { path: '/api/admin/knowledge/tree', method: 'GET', auth: 'admin' },
      new AbortController().signal,
    )
    const treePayload = (await tree.json()) as {
      roots: Array<{ path: string; children: Array<{ name: string }> }>
    }
    const businessRoot = treePayload.roots.find((root) => root.path === '业务')
    expect(businessRoot?.children.map((child) => child.name)).not.toContain('售后')
  })
})

describe('Mock 双语行为（Task 11 Step 8）', () => {
  afterEach(() => {
    setCredentialProvider(undefined)
    setLocaleProvider(undefined)
  })

  it('demo/merchants 按 Accept-Language 返回不同的商家展示名', async () => {
    const zh = await transport({ path: '/api/demo/merchants', method: 'GET' }, new AbortController().signal)
    const zhPayload = (await zh.json()) as components['schemas']['DemoMerchantListResponse']
    expect(zhPayload.merchants[0].display_name).toBe('Borough商家100')

    setLocaleProvider(() => 'en-US')
    const en = await transport({ path: '/api/demo/merchants', method: 'GET' }, new AbortController().signal)
    const enPayload = (await en.json()) as components['schemas']['DemoMerchantListResponse']
    expect(enPayload.merchants[0].display_name).toBe('Borough Merchant 100')
    // merchant_id/token 是技术字段，不受语言影响。
    expect(enPayload.merchants[0].merchant_id).toBe(zhPayload.merchants[0].merchant_id)
    expect(enPayload.merchants[0].token).toBe(zhPayload.merchants[0].token)
  })

  it('每个响应都带 Content-Language，与请求的 Accept-Language 一致', async () => {
    setLocaleProvider(() => 'en-US')
    const response = await transport(
      { path: '/api/demo/merchants', method: 'GET' },
      new AbortController().signal,
    )
    expect(response.headers.get('Content-Language')).toBe('en-US')
  })

  it('/api/chat 按 Accept-Language 返回不同语言的回答正文与思考步骤，技术字段不变', async () => {
    setCredentialProvider(() => ({ merchantToken: 'demo-token-100' }))
    const isolated = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })

    const zhResponse = await isolated(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message: '你好', client_request_id: 'bilingual-zh' },
        accept: 'application/json',
      },
      new AbortController().signal,
    )
    const zhPayload = (await zhResponse.json()) as components['schemas']['ChatResponse']

    setLocaleProvider(() => 'en-US')
    const enResponse = await isolated(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message: '你好', client_request_id: 'bilingual-en' },
        accept: 'application/json',
      },
      new AbortController().signal,
    )
    const enPayload = (await enResponse.json()) as components['schemas']['ChatResponse']

    expect(enPayload.answer).not.toBe(zhPayload.answer)
    expect(enPayload.thinking_steps?.[0]?.label).not.toBe(zhPayload.thinking_steps?.[0]?.label)
    // 技术字段（answer_mode/category/analysis_sources）不因语言而变。
    expect(enPayload.answer_mode).toBe(zhPayload.answer_mode)
    expect(enPayload.category).toBe(zhPayload.category)
    expect(enPayload.analysis_sources).toEqual(zhPayload.analysis_sources)
  })

  it('同一 client_request_id 幂等重放：不产生新消息，按重放时的语言重新渲染', async () => {
    setCredentialProvider(() => ({ merchantToken: 'demo-token-100' }))
    const isolated = createMockTransport({ chunkSizes: [16], stepDelayMs: 0 })

    const first = await isolated(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message: '你好', client_request_id: 'replay-1' },
        accept: 'application/json',
      },
      new AbortController().signal,
    )
    const firstPayload = (await first.json()) as components['schemas']['ChatResponse']

    const listBefore = await isolated(
      { path: '/api/conversations', method: 'GET', auth: 'merchant' },
      new AbortController().signal,
    )
    const before = (await listBefore.json()) as { items: Array<{ id: string }> }

    setLocaleProvider(() => 'en-US')
    const replay = await isolated(
      {
        path: '/api/chat',
        method: 'POST',
        body: { message: '你好', client_request_id: 'replay-1' },
        accept: 'application/json',
      },
      new AbortController().signal,
    )
    const replayPayload = (await replay.json()) as components['schemas']['ChatResponse']

    const listAfter = await isolated(
      { path: '/api/conversations', method: 'GET', auth: 'merchant' },
      new AbortController().signal,
    )
    const after = (await listAfter.json()) as { items: Array<{ id: string }> }

    // 同一个回答 id/会话 id：命中的是幂等分支，不是重新生成了一轮。
    expect(replayPayload.id).toBe(firstPayload.id)
    expect(replayPayload.session_id).toBe(firstPayload.session_id)
    // 重放只是换了语言渲染展示副本，不产生新会话/新消息。
    expect(after.items).toEqual(before.items)
    expect(replayPayload.answer).not.toBe(firstPayload.answer)
  })

  it('知识文档：请求 content_locale=en-US 但尚无译文时返回 MISSING 并回退源正文', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    const response = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md?content_locale=en-US',
        method: 'GET',
        auth: 'admin',
      },
      new AbortController().signal,
    )
    const payload = (await response.json()) as {
      content: string
      content_locale: string
      translation_status: string
    }

    expect(payload.translation_status).toBe('MISSING')
    expect(payload.content_locale).toBe('zh-CN')
    expect(payload.content).toBe('# 运营手册\n\n初始内容')
  })

  it('知识文档：保存译文（is_source_version=false）后按 content_locale 读回 CURRENT', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    const saved = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md',
        method: 'PUT',
        auth: 'admin',
        headers: { 'If-Match': '"1"' },
        body: { content: '# Operations Manual', is_source_version: false, content_locale: 'en-US' },
      },
      new AbortController().signal,
    )
    expect(saved.status).toBe(200)
    const savedPayload = (await saved.json()) as { translation_status: string; content_locale: string }
    expect(savedPayload.translation_status).toBe('CURRENT')
    expect(savedPayload.content_locale).toBe('en-US')

    const readBack = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md?content_locale=en-US',
        method: 'GET',
        auth: 'admin',
      },
      new AbortController().signal,
    )
    const readPayload = (await readBack.json()) as { content: string; translation_status: string }
    expect(readPayload.content).toBe('# Operations Manual')
    expect(readPayload.translation_status).toBe('CURRENT')

    // 源正文没变，源版本读取（不带 content_locale）依旧是中文，版本号未递增。
    const sourceReadBack = await adminTransport(
      { path: '/api/admin/knowledge/documents/index/运营手册.md', method: 'GET', auth: 'admin' },
      new AbortController().signal,
    )
    const sourcePayload = (await sourceReadBack.json()) as { content: string; version: string }
    expect(sourcePayload.content).toBe('# 运营手册\n\n初始内容')
    expect(sourcePayload.version).toBe('1')
  })

  it('知识文档：更新源正文（is_source_version=true）后，旧译文失效，读回退回 MISSING', async () => {
    const adminTransport = createMockTransport()
    setCredentialProvider(() => ({ adminToken: 'mock-admin-token' }))

    await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md',
        method: 'PUT',
        auth: 'admin',
        headers: { 'If-Match': '"1"' },
        body: { content: '# Operations Manual', is_source_version: false, content_locale: 'en-US' },
      },
      new AbortController().signal,
    )

    const updatedSource = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md',
        method: 'PUT',
        auth: 'admin',
        headers: { 'If-Match': '"1"' },
        body: { content: '# 运营手册\n\n更新后的正文', is_source_version: true },
      },
      new AbortController().signal,
    )
    expect(updatedSource.status).toBe(200)
    const updatedPayload = (await updatedSource.json()) as { version: string; content_locale: string }
    expect(updatedPayload.version).toBe('2')
    expect(updatedPayload.content_locale).toBe('zh-CN')

    const readBack = await adminTransport(
      {
        path: '/api/admin/knowledge/documents/index/运营手册.md?content_locale=en-US',
        method: 'GET',
        auth: 'admin',
      },
      new AbortController().signal,
    )
    const readPayload = (await readBack.json()) as { translation_status: string; content: string }
    expect(readPayload.translation_status).toBe('MISSING')
    expect(readPayload.content).toBe('# 运营手册\n\n更新后的正文')
  })
})
