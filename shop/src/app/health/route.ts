// 健康检查：不查库、不调后端、不调 LLM（与 Backend `/api/health` 同一原则）。
export const dynamic = 'force-dynamic'

export function GET() {
  return Response.json({ status: 'ok' })
}
