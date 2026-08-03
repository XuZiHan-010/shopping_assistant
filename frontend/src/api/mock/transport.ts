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

import type { ChatTransport, TransportRequest } from '../transport'
import { CHAT_FIXTURES } from './fixtures.generated'
import { MOCK_MERCHANTS, matchScenario } from './scenarios'

type RawChatResponse = components['schemas']['ChatResponse']

interface MockOptions {
  chunkSizes?: number[]
  stepDelayMs?: number
}

function abortError(): Error {
  const error = new Error('请求已取消')
  error.name = 'AbortError'
  return error
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

export function createMockTransport(options: MockOptions = {}): ChatTransport {
  const resolved: Required<MockOptions> = {
    chunkSizes: options.chunkSizes ?? [5, 13, 3, 29, 7],
    stepDelayMs: options.stepDelayMs ?? 12,
  }

  // 每个 transport 实例持有自己的会话表。放模块级会让状态在测试之间泄漏，
  // 「删除后列表为空」这类断言就会依赖测试执行顺序。
  const conversations = new Map<
    string,
    {
      id: string
      title: string
      createdAt: string
      messages: components['schemas']['ConversationMessage'][]
    }
  >()

  return async (request: TransportRequest, signal: AbortSignal): Promise<Response> => {
    if (signal.aborted) throw abortError()

    if (request.path === '/api/demo/merchants') {
      // 契约里这个键是 merchants，不是 items——与 ConversationListResponse 不同，
      // 别搞混。satisfies 让键名或字段漂移在 typecheck 阶段就炸掉。
      return jsonResponse({
        merchants: [...MOCK_MERCHANTS],
      } satisfies components['schemas']['DemoMerchantListResponse'])
    }

    if (request.path === '/api/chat' && request.method === 'POST') {
      const body = request.body as { message: string; session_id?: string | null }
      const fixture = CHAT_FIXTURES[matchScenario(body.message)] as RawChatResponse
      const sessionId = body.session_id ?? fixture.session_id
      const now = new Date().toISOString()
      const answerId = crypto.randomUUID()

      const existing = conversations.get(sessionId)
      const record = existing ?? {
        id: sessionId,
        title: body.message.slice(0, 20),
        createdAt: now,
        messages: [],
      }
      // 记下真实往返，历史会话点开才有内容可载入。
      record.messages.push(
        { id: crypto.randomUUID(), role: 'user', content: body.message, created_at: now },
        { id: answerId, role: 'assistant', content: fixture.answer, created_at: now },
      )
      conversations.set(sessionId, record)

      const payload = { ...fixture, session_id: sessionId, id: answerId }

      if (request.accept === 'application/json') return jsonResponse(payload)
      return sseResponse(payload, signal, resolved)
    }

    if (request.path === '/api/conversations' && request.method === 'GET') {
      const items: components['schemas']['ConversationSummary'][] = [
        ...conversations.values(),
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

    const detailMatch = /^\/api\/conversations\/([^/]+)$/.exec(request.path)
    if (detailMatch) {
      const id = detailMatch[1]
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
