/**
 * Mock ChatTransport。
 *
 * 只 mock「传输」：载荷全部是后端 FakeAgent 的真实输出（fixture 镜像），
 * 上层的 sse.ts、Adapter、Store 走的都是真实代码路径。
 *
 * 刻意按小字节块吐出，切断多字节 UTF-8 和事件边界——后端对自己的解析器也是
 * 这么测的（后端方案 §14），前后端对称。
 */
import type { components } from '@/api/generated'

import { buildAuthHeaders } from '../credentials'
import type { ChatTransport, TransportRequest } from '../transport'
import { CHAT_FIXTURES } from './fixtures.generated'
import { MOCK_MERCHANTS, matchScenario } from './scenarios'
import { BUSINESS_SECTIONS } from '@/utils/knowledgeTree'

type MockKnowledgeDocument = { content: string; read_only: boolean; version: string }
type MockKnowledgeNode = components['schemas']['KnowledgeTreeNode']

type RawChatResponse = components['schemas']['ChatResponse']

interface MockOptions {
  chunkSizes?: number[]
  stepDelayMs?: number
}

/**
 * 必须是真正的 `DOMException`，不能是「改了 `.name` 的普通 `Error`」。
 *
 * `toAppError`（`src/api/errors.ts`）用 `error instanceof DOMException &&
 * error.name === 'AbortError'` 识别取消——这是它唯一的判据，不会退化成看
 * `.name` 字符串。真实浏览器的 `fetch`/`AbortController` 在中止时抛出的正是
 * `DOMException`，Mock 传输如果只是给普通 `Error` 改名，形状就和真实环境不
 * 对称：Store 的 `runRound` 会把它误判成 `INTERNAL_ERROR`，取消操作在 Mock
 * 下看起来永远在报错，而这条路径在真实后端下其实是好的——问题只出在 Mock
 * 自己的仿真不到位。
 */
function abortError(): DOMException {
  return new DOMException('请求已取消', 'AbortError')
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

/**
 * `ErrorResponse` 的 required 字段含 `request_id`、`retryable`（generated.ts
 * 第 317-332 行），Mock 也必须给全，否则前端错误处理路径拿到的载荷和真实
 * 后端形状不一致。这里的 request_id 是确定性占位值，不追求可追溯性。
 */
function errorResponse(
  code: components['schemas']['ErrorCode'],
  message: string,
  status: number,
): Response {
  return jsonResponse(
    {
      code,
      message,
      request_id: 'mock-request-id',
      retryable: false,
    } satisfies components['schemas']['ErrorResponse'],
    status,
  )
}

function mockDocumentNode(path: string, document: MockKnowledgeDocument): MockKnowledgeNode {
  return {
    name: path.split('/').at(-1) ?? path,
    path,
    node_type: 'document',
    read_only: document.read_only,
    size: document.content.length,
    version: document.version,
    children: [],
  }
}

/**
 * 与真实后端 `directory_version`（`backend/app/knowledge/versioning.py`）同样的思路：
 * 目录版本由子节点路径与版本拼接派生，而不是单独维护一个计数器——这样文档
 * 增删或重命名后，父目录的 If-Match 版本会自动跟着变，不需要额外的失效逻辑。
 */
function mockDirectoryVersion(children: MockKnowledgeNode[]): string {
  return children.length
    ? children
        .map((child) => `${child.path}@${child.version}`)
        .sort()
        .join('|')
    : 'empty'
}

function mockDirectoryNode(
  path: string,
  readOnly: boolean,
  children: MockKnowledgeNode[],
): MockKnowledgeNode {
  return {
    name: path.split('/').at(-1) ?? path,
    path,
    node_type: 'directory',
    read_only: readOnly,
    size: children.reduce((sum, child) => sum + child.size, 0),
    version: mockDirectoryVersion(children),
    children,
  }
}

function mockIndexRoot(knowledgeDocuments: Map<string, MockKnowledgeDocument>): MockKnowledgeNode {
  const children = [...knowledgeDocuments.entries()]
    .filter(([path]) => path.startsWith('index/') && path.split('/').length === 2)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([path, document]) => mockDocumentNode(path, document))
  return mockDirectoryNode('index', false, children)
}

function mockBusinessRoot(
  knowledgeDocuments: Map<string, MockKnowledgeDocument>,
): MockKnowledgeNode {
  const domainNames = new Set<string>()
  for (const path of knowledgeDocuments.keys()) {
    const segments = path.split('/')
    if (
      segments.length === 4 &&
      segments[0] === '业务' &&
      (BUSINESS_SECTIONS as readonly string[]).includes(segments[2])
    ) {
      domainNames.add(segments[1])
    }
  }

  const domains = [...domainNames]
    .sort((a, b) => a.localeCompare(b))
    .map((domain) => {
      const sections = BUSINESS_SECTIONS.map((section) => {
        const prefix = `业务/${domain}/${section}/`
        const children = [...knowledgeDocuments.entries()]
          .filter(([path]) => path.startsWith(prefix))
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([path, document]) => mockDocumentNode(path, document))
        return mockDirectoryNode(`业务/${domain}/${section}`, false, children)
      })
      return mockDirectoryNode(`业务/${domain}`, false, sections)
    })
  return mockDirectoryNode('业务', false, domains)
}

function mockMemoryRoot(knowledgeDocuments: Map<string, MockKnowledgeDocument>): MockKnowledgeNode {
  const byMerchant = new Map<string, Array<[string, MockKnowledgeDocument]>>()
  for (const [path, document] of knowledgeDocuments) {
    const segments = path.split('/')
    if (segments.length === 4 && segments[0] === 'memory' && segments[1] === 'merchants') {
      const merchantId = segments[2]
      const entries = byMerchant.get(merchantId) ?? []
      entries.push([path, document])
      byMerchant.set(merchantId, entries)
    }
  }
  const merchants = [...byMerchant.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([merchantId, entries]) => {
      const children = entries
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([path, document]) => mockDocumentNode(path, document))
      return mockDirectoryNode(`memory/merchants/${merchantId}`, true, children)
    })
  return mockDirectoryNode('memory', true, [mockDirectoryNode('memory/merchants', true, merchants)])
}

function mockKnowledgeTree(
  knowledgeDocuments: Map<string, MockKnowledgeDocument>,
): components['schemas']['KnowledgeTreeResponse'] {
  return {
    roots: [
      mockIndexRoot(knowledgeDocuments),
      mockBusinessRoot(knowledgeDocuments),
      mockMemoryRoot(knowledgeDocuments),
    ],
  }
}

function findMockDomainNode(
  knowledgeDocuments: Map<string, MockKnowledgeDocument>,
  name: string,
): MockKnowledgeNode | undefined {
  return (mockBusinessRoot(knowledgeDocuments).children ?? []).find(
    (domain) => domain.name === name,
  )
}

function encodeSse(fixture: RawChatResponse): Uint8Array {
  let text = ''
  for (const step of fixture.thinking_steps ?? []) {
    text += `event: step\ndata: ${JSON.stringify(step)}\n\n`
  }
  text += ': keep-alive\n\n'
  text += `event: done\ndata: ${JSON.stringify(fixture)}\n\n`
  return new TextEncoder().encode(text)
}

function sseResponse(
  fixture: RawChatResponse,
  signal: AbortSignal,
  options: Required<MockOptions>,
): Response {
  const bytes = encodeSse(fixture)

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let offset = 0
      let index = 0

      while (offset < bytes.length) {
        if (signal.aborted) {
          controller.error(abortError())
          return
        }

        const size = options.chunkSizes[index % options.chunkSizes.length]
        controller.enqueue(bytes.slice(offset, offset + size))
        offset += size
        index += 1

        if (options.stepDelayMs > 0) {
          await new Promise((resolve) => setTimeout(resolve, options.stepDelayMs))
        }
      }

      controller.close()
    },
  })

  return new Response(stream, {
    status: 200,
    headers: { 'content-type': 'text/event-stream; charset=utf-8' },
  })
}

type ConversationRecord = {
  id: string
  title: string
  createdAt: string
  messages: components['schemas']['ConversationMessage'][]
}

function historyAnswerPayload(
  payload: RawChatResponse,
): components['schemas']['ConversationAnswerPayload'] {
  const rows = payload.data_rows ?? []
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))]
  return {
    answer_id: payload.id,
    answer_mode: payload.answer_mode,
    thinking_steps: payload.thinking_steps ?? [],
    quality_status: payload.quality_status,
    quality_attempts: payload.quality_attempts,
    quality_notes: payload.quality_notes ?? [],
    degraded: payload.degraded,
    degraded_reason: payload.degraded_reason,
    is_adopted: false,
    reaction: null,
    columns,
    total_rows: payload.total_rows ?? null,
    truncated: payload.truncated ?? null,
  }
}

/**
 * 没有可用凭证（未注册 `setCredentialProvider`，或注册了但没给 token）时落进
 * 这个固定桶。真实后端遇到这种情况会直接 401——Mock 不模拟那条拒绝路径
 * （401 场景由调用方自己打桩传输层，见 `AssistantView.spec.ts`），只需要保证
 * 「没带身份」的请求彼此还能看到同一张表，不破坏历史上不关心鉴权的用例。
 */
const ANONYMOUS_TENANT_KEY = '(no-authorization-header)'
const MOCK_ADMIN_TOKEN = 'mock-admin-token'

/**
 * 按「这次请求会带哪个 Authorization 头」分桶，而不是直接读 `request.auth`
 * 这个租户范围枚举——真实商家之间的区别在 Token 本身，同为 `'merchant'`
 * 范围的两个商家必须落进两张不同的表。这里复用 `buildAuthHeaders`，与
 * `createFetchTransport` 装配请求头走的是同一份代码，保证 Mock 与真实
 * 传输对「这次请求的身份是什么」这件事的判断口径一致。
 */
function tenantKeyFor(request: TransportRequest): string {
  try {
    const headers = buildAuthHeaders(request.auth ?? 'merchant')
    return headers.Authorization ?? headers['X-Admin-Token'] ?? ANONYMOUS_TENANT_KEY
  } catch {
    return ANONYMOUS_TENANT_KEY
  }
}

export function createMockTransport(options: MockOptions = {}): ChatTransport {
  const resolved: Required<MockOptions> = {
    chunkSizes: options.chunkSizes ?? [5, 13, 3, 29, 7],
    stepDelayMs: options.stepDelayMs ?? 12,
  }

  // 每个 transport 实例持有自己的租户表集合。放模块级会让状态在测试之间
  // 泄漏，「删除后列表为空」这类断言就会依赖测试执行顺序。
  // 一层 Map 套一层 Map：外层按 Authorization 头分商家，内层才是该商家自己
  // 的会话表——真实后端按 Token 过滤，Mock 至少要在传输实例这一级做到同样
  // 的隔离，Playwright 的隔离 e2e 才不会在假绿的 Mock 上通过。
  const conversationsByTenant = new Map<string, Map<string, ConversationRecord>>()
  const dailyReportsByTenant = new Map<string, components['schemas']['DailyReportResponse']>()
  const knowledgeDocuments = new Map([
    ['index/运营手册.md', { content: '# 运营手册\n\n初始内容', read_only: false, version: '1' }],
    [
      'memory/merchants/demo/TRADE.md',
      { content: '本轮自动沉淀：关注退款率。', read_only: true, version: '1' },
    ],
  ])

  function conversationsFor(request: TransportRequest): Map<string, ConversationRecord> {
    const key = tenantKeyFor(request)
    let table = conversationsByTenant.get(key)
    if (!table) {
      table = new Map()
      conversationsByTenant.set(key, table)
    }
    return table
  }

  function dailyReportFor(request: TransportRequest): components['schemas']['DailyReportResponse'] {
    const tenantKey = tenantKeyFor(request)
    const existing = dailyReportsByTenant.get(tenantKey)
    if (existing) return existing

    const report = {
      answer_id: crypto.randomUUID(),
      report_date: '2026-08-20',
      metrics: [
        { metric_code: 'gmv', display_name: '成交金额', unit: '元', value: '12680.00' },
        { metric_code: 'ordering_user_count', display_name: '下单用户数', unit: '人', value: 86 },
        { metric_code: 'order_count', display_name: '订单量', unit: '单', value: 92 },
        {
          metric_code: 'successful_order_count',
          display_name: '交易成功订单量',
          unit: '单',
          value: 75,
        },
        { metric_code: 'return_count', display_name: '退货量', unit: '单', value: 4 },
        { metric_code: 'refund_amount', display_name: '退款金额', unit: '元', value: '385.00' },
      ],
      suggestions: [
        '近 7 日存在退款金额，建议优先查看退货退款明细，定位高频原因并优化发货、售后说明。',
        '建议继续关注 GMV、交易成功订单量和优惠使用效果，挑选转化较好的商品加大运营。',
      ],
      degraded: false,
      degraded_reason: null,
    } satisfies components['schemas']['DailyReportResponse']
    dailyReportsByTenant.set(tenantKey, report)
    return report
  }

  return async (request: TransportRequest, signal: AbortSignal): Promise<Response> => {
    if (signal.aborted) throw abortError()

    if (request.path.split('?')[0].startsWith('/api/exports/') && request.method === 'GET') {
      return new Response('order_no,paid_amount\nBR20260803-0001,258.00\n', {
        status: 200,
        headers: {
          'content-type': 'text/csv; charset=utf-8',
          'content-disposition': 'attachment; filename="borough-detail.csv"',
        },
      })
    }

    if (request.path === '/api/demo/merchants') {
      // 契约里这个键是 merchants，不是 items——与 ConversationListResponse 不同，
      // 别搞混。satisfies 让键名或字段漂移在 typecheck 阶段就炸掉。
      return jsonResponse({
        merchants: [...MOCK_MERCHANTS],
      } satisfies components['schemas']['DemoMerchantListResponse'])
    }

    if (request.path === '/api/reports/daily' && request.method === 'GET') {
      return jsonResponse(dailyReportFor(request))
    }

    const pathname = request.path.split('?')[0]

    if (pathname.startsWith('/api/admin/analytics/chatbi/')) {
      if (tenantKeyFor(request) !== MOCK_ADMIN_TOKEN) {
        return errorResponse('AUTH_REQUIRED', '管理员令牌无效', 401)
      }

      if (pathname === '/api/admin/analytics/chatbi/overview' && request.method === 'GET') {
        return jsonResponse({
          start_date: '2026-08-17',
          end_date: '2026-08-23',
          answer_total: 18,
          business_question_total: 15,
          feedback_total: 7,
          thinking_sample_count: 16,
          adoption_rate: null,
          user_accuracy_rate: 0.75,
          system_accuracy_rate: 0.875,
          avg_thinking_ms: 2250,
          hit_rate: 0.8,
          failure_rate: 0.05,
          daily: [
            {
              stat_date: '2026-08-22',
              answer_total: 7,
              adoption_rate: 0.5,
              user_accuracy_rate: null,
              system_accuracy_rate: 1,
              avg_thinking_ms: 2100,
              hit_rate: 1,
              failure_rate: 0,
            },
            {
              stat_date: '2026-08-23',
              answer_total: 11,
              adoption_rate: null,
              user_accuracy_rate: 0.75,
              system_accuracy_rate: 0.8,
              avg_thinking_ms: 2400,
              hit_rate: null,
              failure_rate: 0.1,
            },
          ],
        } satisfies components['schemas']['ChatBiOverviewResponse'])
      }

      if (pathname === '/api/admin/analytics/chatbi/categories' && request.method === 'GET') {
        return jsonResponse({
          start_date: '2026-08-17',
          end_date: '2026-08-23',
          items: [
            {
              category: 'TRADE',
              category_display_name: '交易分析',
              answer_total: 12,
              adoption_rate: null,
              user_accuracy_rate: 0.75,
              system_accuracy_rate: 0.9,
              avg_thinking_ms: 2200,
              hit_rate: 0.9,
              failure_rate: 0,
            },
            {
              category: 'UNKNOWN',
              category_display_name: '未分类',
              answer_total: 6,
              adoption_rate: 0,
              user_accuracy_rate: null,
              system_accuracy_rate: null,
              avg_thinking_ms: null,
              hit_rate: null,
              failure_rate: 1 / 6,
            },
          ],
        } satisfies components['schemas']['ChatBiCategoriesResponse'])
      }

      if (pathname === '/api/admin/analytics/chatbi/rollup' && request.method === 'POST') {
        const body = request.body as components['schemas']['ChatBiWindow']
        return jsonResponse({
          start_date: body.start_date,
          end_date: body.end_date,
          rows_written: 4,
        } satisfies components['schemas']['ChatBiRollupResponse'])
      }
    }

    if (request.path === '/api/admin/knowledge/tree' && request.method === 'GET') {
      if (tenantKeyFor(request) !== MOCK_ADMIN_TOKEN) {
        return errorResponse('AUTH_REQUIRED', '管理员令牌无效', 401)
      }
      return jsonResponse(mockKnowledgeTree(knowledgeDocuments))
    }

    if (request.path === '/api/admin/knowledge/documents' && request.method === 'POST') {
      if (tenantKeyFor(request) !== MOCK_ADMIN_TOKEN) {
        return errorResponse('AUTH_REQUIRED', '管理员令牌无效', 401)
      }
      const payload = request.body as components['schemas']['KnowledgeDocumentRequest']
      if (knowledgeDocuments.has(payload.path)) {
        return errorResponse('WIKI_NODE_EXISTS', '同名文档已存在', 409)
      }
      const created: MockKnowledgeDocument = {
        content: payload.content,
        read_only: false,
        version: '1',
      }
      knowledgeDocuments.set(payload.path, created)
      return jsonResponse(
        {
          path: payload.path,
          ...created,
        } satisfies components['schemas']['KnowledgeDocumentResponse'],
        201,
      )
    }

    const businessDomainMatch =
      request.path.split('?')[0] === '/api/admin/knowledge/business-domains'
    if (businessDomainMatch) {
      if (tenantKeyFor(request) !== MOCK_ADMIN_TOKEN) {
        return errorResponse('AUTH_REQUIRED', '管理员令牌无效', 401)
      }
      const query = new URLSearchParams(request.path.split('?')[1] ?? '')

      if (request.method === 'POST') {
        const payload = request.body as components['schemas']['BusinessDomainRequest']
        if (findMockDomainNode(knowledgeDocuments, payload.name)) {
          return errorResponse('WIKI_NODE_EXISTS', '同名业务域已存在', 409)
        }
        for (const section of BUSINESS_SECTIONS) {
          knowledgeDocuments.set(`业务/${payload.name}/${section}/待补充.md`, {
            content: `# ${payload.name}／${section}\n\n资料尚未完整，请由管理员补充。`,
            read_only: false,
            version: '1',
          })
        }
        const domain = findMockDomainNode(knowledgeDocuments, payload.name)
        return jsonResponse(domain, 201)
      }

      const name = query.get('name') ?? ''
      const domain = findMockDomainNode(knowledgeDocuments, name)
      if (!domain) return errorResponse('WIKI_NODE_NOT_FOUND', '业务域不存在', 404)
      const ifMatch = request.headers?.['If-Match']
      if (!ifMatch) return errorResponse('WIKI_VERSION_REQUIRED', '缺少 If-Match 版本', 428)
      if (ifMatch !== `"${domain.version}"`) {
        return errorResponse('WIKI_VERSION_CONFLICT', '业务域已被其他维护者更新', 412)
      }

      if (request.method === 'PUT') {
        const payload = request.body as components['schemas']['BusinessDomainRenameRequest']
        if (findMockDomainNode(knowledgeDocuments, payload.new_name)) {
          return errorResponse('WIKI_NODE_EXISTS', '同名业务域已存在', 409)
        }
        const prefix = `业务/${name}/`
        for (const [path, document] of [...knowledgeDocuments.entries()]) {
          if (path.startsWith(prefix)) {
            knowledgeDocuments.delete(path)
            knowledgeDocuments.set(
              `业务/${payload.new_name}/${path.slice(prefix.length)}`,
              document,
            )
          }
        }
        return jsonResponse(findMockDomainNode(knowledgeDocuments, payload.new_name))
      }

      if (request.method === 'DELETE') {
        const prefix = `业务/${name}/`
        for (const path of [...knowledgeDocuments.keys()]) {
          if (path.startsWith(prefix)) knowledgeDocuments.delete(path)
        }
        return new Response(null, { status: 204 })
      }
    }

    const knowledgePathMatch = /^\/api\/admin\/knowledge\/documents\/(.+)$/.exec(request.path)
    if (knowledgePathMatch) {
      if (tenantKeyFor(request) !== MOCK_ADMIN_TOKEN) {
        return errorResponse('AUTH_REQUIRED', '管理员令牌无效', 401)
      }
      const path = decodeURIComponent(knowledgePathMatch[1])
      const document = knowledgeDocuments.get(path)
      if (!document) return errorResponse('WIKI_NODE_NOT_FOUND', '文档不存在', 404)

      if (request.method === 'GET') {
        return jsonResponse({
          path,
          ...document,
        } satisfies components['schemas']['KnowledgeDocumentResponse'])
      }

      if (request.method === 'DELETE') {
        const ifMatch = request.headers?.['If-Match']
        if (!ifMatch) return errorResponse('WIKI_VERSION_REQUIRED', '缺少 If-Match 版本', 428)
        if (ifMatch !== `"${document.version}"`) {
          return errorResponse('WIKI_VERSION_CONFLICT', '文档已被其他维护者更新', 412)
        }
        knowledgeDocuments.delete(path)
        return new Response(null, { status: 204 })
      }

      if (request.method === 'PUT') {
        if (request.headers?.['If-Match'] !== `"${document.version}"`) {
          return errorResponse('WIKI_VERSION_CONFLICT', '文档已被其他维护者更新', 412)
        }
        const content = (request.body as components['schemas']['KnowledgeDocumentUpdateRequest'])
          .content
        const updated = { ...document, content, version: String(Number(document.version) + 1) }
        knowledgeDocuments.set(path, updated)
        return jsonResponse({
          path,
          ...updated,
        } satisfies components['schemas']['KnowledgeDocumentResponse'])
      }
    }

    if (request.path === '/api/chat' && request.method === 'POST') {
      const body = request.body as { message: string; session_id?: string | null }
      const fixture = CHAT_FIXTURES[matchScenario(body.message)] as RawChatResponse
      const sessionId = body.session_id ?? fixture.session_id
      const now = new Date().toISOString()
      const answerId = crypto.randomUUID()
      const conversations = conversationsFor(request)

      const existing = conversations.get(sessionId)
      const record = existing ?? {
        id: sessionId,
        title: body.message.slice(0, 20),
        createdAt: now,
        messages: [],
      }
      const payload = { ...fixture, session_id: sessionId, id: answerId }
      // 记下真实往返，历史会话点开才有内容可载入；助手侧只保存与后端详情
      // 契约一致的脱敏载荷，不能把 data_rows / export 放进历史消息。
      record.messages.push(
        { id: crypto.randomUUID(), role: 'user', content: body.message, created_at: now },
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: fixture.answer,
          created_at: now,
          answer_payload: historyAnswerPayload(payload),
        },
      )
      conversations.set(sessionId, record)

      if (request.accept === 'application/json') return jsonResponse(payload)
      return sseResponse(payload, signal, resolved)
    }

    const feedbackMatch = /^\/api\/answers\/([^/]+)\/feedback$/.exec(request.path)
    if (feedbackMatch && request.method === 'POST') {
      const body = request.body as components['schemas']['FeedbackRequest']
      const answerId = feedbackMatch[1]
      for (const conversation of conversationsFor(request).values()) {
        for (const message of conversation.messages) {
          if (message.answer_payload?.answer_id !== answerId) continue
          message.answer_payload = {
            ...message.answer_payload,
            is_adopted: body.is_adopted,
            reaction: body.reaction ?? null,
          }
        }
      }
      return jsonResponse({
        answer_id: answerId,
        is_adopted: body.is_adopted,
        reaction: body.reaction ?? null,
      } satisfies components['schemas']['FeedbackResponse'])
    }

    // listConversations 现在带 ?limit=，这里只按路径部分匹配，query 由真实后端解释。
    if (pathname === '/api/conversations' && request.method === 'GET') {
      const items: components['schemas']['ConversationSummary'][] = [
        ...conversationsFor(request).values(),
      ].map((item) => ({
        id: item.id,
        title: item.title,
        created_at: item.createdAt,
        updated_at: item.createdAt,
      }))
      return jsonResponse({
        items,
        limit: 20,
        offset: 0,
      } satisfies components['schemas']['ConversationListResponse'])
    }

    const detailMatch = /^\/api\/conversations\/([^/]+)$/.exec(pathname)
    if (detailMatch) {
      const id = detailMatch[1]
      const conversations = conversationsFor(request)
      if (request.method === 'DELETE') {
        conversations.delete(id)
        return new Response(null, { status: 204 })
      }

      const found = conversations.get(id)
      if (!found) return errorResponse('NOT_FOUND', '会话不存在', 404)

      return jsonResponse({
        id: found.id,
        title: found.title,
        messages: found.messages,
        created_at: found.createdAt,
        updated_at: found.createdAt,
      } satisfies components['schemas']['ConversationDetailResponse'])
    }

    return errorResponse('NOT_FOUND', `Mock 未覆盖 ${request.path}`, 404)
  }
}
