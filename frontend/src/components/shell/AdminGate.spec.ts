import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setCredentialProvider } from '@/api/credentials'
import { AppError } from '@/api/errors'
import { createFetchTransport, setChatTransport, type TransportRequest } from '@/api/transport'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useLocaleStore } from '@/stores/locale'
import KnowledgeBaseView from '@/views/KnowledgeBaseView.vue'

import AdminGate from './AdminGate.vue'

const SLOT = '<p data-testid="protected">受保护内容</p>'

function mountGate(pinia = createPinia()) {
  setActivePinia(pinia)
  useLocaleStore().setLocale('zh-CN')
  return mount(AdminGate, { global: { plugins: [pinia, i18n] }, slots: { default: SLOT } })
}

describe('AdminGate', () => {
  const requests: TransportRequest[] = []

  beforeEach(() => {
    requests.length = 0
    setChatTransport(async (request) => {
      requests.push(request)
      return Response.json({ roots: [] })
    })
  })

  afterEach(() => {
    setChatTransport(undefined)
    setCredentialProvider(undefined)
  })

  it('未持令牌时只显示令牌入口，不渲染受保护内容，也不发任何 /api/admin/* 请求', async () => {
    const wrapper = mountGate()
    await flushPromises()

    expect(wrapper.find('[data-testid="admin-token-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(false)
    expect(requests).toHaveLength(0)
  })

  it('令牌入口是页内卡片而不是模态框：不标 aria-modal，侧栏与 Ctrl + J 仍可用', async () => {
    const wrapper = mountGate()
    await flushPromises()

    expect(wrapper.find('[aria-modal="true"]').exists()).toBe(false)
  })

  it('提交有效令牌后验证目录树并放行插槽内容', async () => {
    const wrapper = mountGate()

    await wrapper.get('[data-testid="admin-token-input"]').setValue('admin-secret')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(requests.map((r) => `${r.method} ${r.path}`)).toEqual(['GET /api/admin/knowledge/tree'])
    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="admin-token-input"]').exists()).toBe(false)
  })

  it('令牌被后端拒绝时回到入口、提示错误并清掉令牌', async () => {
    setChatTransport(async () => {
      throw new AppError('AUTH_REQUIRED', '管理员令牌无效', { status: 401 })
    })
    const pinia = createPinia()
    const wrapper = mountGate(pinia)

    await wrapper.get('[data-testid="admin-token-input"]').setValue('bad')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('管理员令牌无效')
    expect(useKnowledgeStore(pinia).adminToken).toBe('')
  })

  it('网络或 5xx 失败时保留令牌、提示可重试，重试成功后放行', async () => {
    let fail = true
    setChatTransport(async () => {
      if (fail) throw new AppError('NETWORK', '网络不可用', { status: 503 })
      return Response.json({ roots: [] })
    })
    const pinia = createPinia()
    const wrapper = mountGate(pinia)

    await wrapper.get('[data-testid="admin-token-input"]').setValue('admin-secret')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(useKnowledgeStore(pinia).adminToken).toBe('admin-secret')
    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="admin-gate-retry-error"]').exists()).toBe(true)

    fail = false
    await wrapper.get('[data-testid="admin-gate-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(true)
  })

  it('403 与 401 一样视为令牌被拒：清令牌并回到入口', async () => {
    setChatTransport(async () => {
      throw new AppError('FORBIDDEN', '无权限', { status: 403 })
    })
    const pinia = createPinia()
    const wrapper = mountGate(pinia)
    await wrapper.get('[data-testid="admin-token-input"]').setValue('bad')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(useKnowledgeStore(pinia).adminToken).toBe('')
    expect(wrapper.find('[data-testid="admin-token-input"]').exists()).toBe(true)
  })

  it('已持令牌重新挂载时，验证完成前不渲染受保护内容（坏令牌不闪现）', async () => {
    let release: (r: Response) => void = () => undefined
    setChatTransport(() => new Promise<Response>((resolve) => (release = resolve)))
    const pinia = createPinia()
    setActivePinia(pinia)
    useKnowledgeStore().setAdminToken('stale-token')
    const wrapper = mountGate(pinia)
    await flushPromises()

    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="admin-gate-verifying"]').exists()).toBe(true)

    release(Response.json({ roots: [] }))
    await flushPromises()
    expect(wrapper.find('[data-testid="protected"]').exists()).toBe(true)
  })

  it('令牌不进入 URL，也不写入 localStorage / sessionStorage', async () => {
    const wrapper = mountGate()
    await wrapper.get('[data-testid="admin-token-input"]').setValue('admin-secret-xyz')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(requests.every((r) => !r.path.includes('admin-secret-xyz'))).toBe(true)
    expect(window.location.href).not.toContain('admin-secret-xyz')
    expect(JSON.stringify({ ...localStorage })).not.toContain('admin-secret-xyz')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('admin-secret-xyz')
  })
})

describe('凭证隔离：商家会话与管理员令牌互不混用', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    setChatTransport(undefined)
    setCredentialProvider(undefined)
  })

  it('管理请求只带 X-Admin-Token，不带商家会话凭证', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    const knowledge = useKnowledgeStore(pinia)
    auth.sessionId = 'session-abc'
    setCredentialProvider(() => ({
      merchantToken: 'merchant-token-100',
      adminToken: knowledge.adminToken,
      sessionId: auth.sessionId ?? undefined,
    }))
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.test')
    // 请求头在真实 fetch transport 里才装配，所以这里走 createFetchTransport，桩掉全局 fetch。
    const seen: Array<Record<string, string>> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: { headers: Record<string, string> }) => {
        seen.push(init.headers)
        return Response.json({ roots: [] })
      }),
    )
    setChatTransport(createFetchTransport())
    useLocaleStore().setLocale('zh-CN')

    const wrapper = mount(KnowledgeBaseView, { global: { plugins: [pinia, i18n] } })
    await wrapper.get('[data-testid="admin-token-input"]').setValue('admin-secret')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(seen.length).toBeGreaterThan(0)
    for (const headers of seen) {
      expect(headers['X-Admin-Token']).toBe('admin-secret')
      expect(headers.Authorization).toBeUndefined()
      expect(headers['X-Session-Id']).toBeUndefined()
      expect(Object.values(headers)).not.toContain('session-abc')
      expect(Object.values(headers)).not.toContain('merchant-token-100')
    }
  })

  it('反向：商家请求不带 X-Admin-Token，管理员令牌值不出现在任何请求头', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore(pinia)
    const knowledge = useKnowledgeStore(pinia)
    auth.sessionId = 'session-abc'
    knowledge.setAdminToken('admin-secret')
    setCredentialProvider(() => ({
      merchantToken: 'merchant-token-100',
      adminToken: knowledge.adminToken,
      sessionId: auth.sessionId ?? undefined,
    }))
    vi.stubEnv('VITE_API_BASE_URL', 'http://api.test')
    const seen: Array<Record<string, string>> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: { headers: Record<string, string> }) => {
        seen.push(init.headers)
        return Response.json({})
      }),
    )
    const transport = createFetchTransport()
    const signal = new AbortController().signal
    await transport(
      {
        path: '/api/v2/merchant/inventory',
        method: 'GET', // TransportRequest 的类型尚未列出 merchant-session，运行时 buildAuthHeaders 支持它。
        auth: 'merchant-session' as 'merchant',
      },
      signal,
    )
    await transport({ path: '/api/v2/merchant/sessions', method: 'POST', auth: 'merchant' }, signal)

    expect(seen).toHaveLength(2)
    for (const headers of seen) {
      expect(headers['X-Admin-Token']).toBeUndefined()
      expect(Object.values(headers)).not.toContain('admin-secret')
    }
    expect(seen[0]!['X-Session-Id']).toBe('session-abc')
    expect(seen[1]!.Authorization).toBe('Bearer merchant-token-100')
  })
})
