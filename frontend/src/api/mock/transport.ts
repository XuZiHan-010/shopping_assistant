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

    if (request.path === '/api/admin/knowledge/tree' && request.method === 'GET') {
      if (tenantKeyFor(request) !== MOCK_ADMIN_TOKEN) {
        return errorResponse('AUTH_REQUIRED', '管理员令牌无效', 401)
      }
      return jsonResponse({
        roots: [
          {
            name: 'index',
            path: 'index',
            node_type: 'directory',
            read_only: false,
            size: 1,
            version: 'index-v1',
            children: [
              {
                name: '运营手册.md',
                path: 'index/运营手册.md',
                node_type: 'document',
                read_only: false,
                size: 10,
                version: '1',
                children: [],
              },
            ],
          },
          {
            name: '业务',
            path: '业务',
            node_type: 'directory',
            read_only: false,
            size: 0,
            version: 'business-v1',
            children: [],
          },
          {
            name: 'memory',
            path: 'memory',
            node_type: 'directory',
            read_only: true,
            size: 1,
            version: 'memory-v1',
            children: [
              {
                name: 'TRADE.md',
                path: 'memory/merchants/demo/TRADE.md',
                node_type: 'document',
                read_only: true,
                size: 12,
                version: '1',
                children: [],
              },
            ],
          },
        ],
      } satisfies components['schemas']['KnowledgeTreeResponse'])
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
    const pathname = request.path.split('?')[0]

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
