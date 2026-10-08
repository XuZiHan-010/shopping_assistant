import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useRailStore } from '@/stores/rail'

import MerchantShell from './MerchantShell.vue'

const MERCHANTS = [{ merchantId: 'm-100', displayName: 'Borough商家100', token: 't-100' }]
const OTHER = { merchantId: 'm-101', displayName: 'Borough商家101', token: 't-101' }

let homeMounts = 0

/** 与真实路由表同名的子路由，组件换成桩，只测外壳本身。 */
function shellRoutes() {
  const stub = { template: '<div />' }
  return [
    {
      path: '/',
      component: MerchantShell,
      children: [
        {
          path: '',
          name: 'home',
          component: {
            template: '<h1 data-testid="child">首页子页</h1>',
            mounted() {
              homeMounts += 1
            },
          },
        },
        ...[
          ['catalog', 'catalog'],
          ['orders', 'orders'],
          ['inventory', 'inventory'],
          ['approvals', 'approval-list'],
          ['approvals/:draftId', 'approval'],
          ['after-sales', 'after-sales'],
          ['customer-signals', 'customer-signals'],
          ['memories', 'merchant-memory'],
          ['knowledge-base', 'knowledge-base'],
          ['ops-status', 'ops-status'],
        ].map(([path, name]) => ({ path: path!, name: name!, component: stub })),
      ],
    },
  ]
}

async function mountShell(options: { brokenStorage?: boolean } = {}) {
  if (options.brokenStorage) {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
  }
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.merchants = [...MERCHANTS]
  auth.selected = MERCHANTS[0]
  const router = createRouter({ history: createMemoryHistory(), routes: shellRoutes() })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(
    { template: '<RouterView />' },
    {
      attachTo: document.body,
      global: { plugins: [pinia, i18n, router] },
    },
  )
  await flushPromises()
  return { wrapper, router, auth }
}

/**
 * 助手栏打开时会拉会话目录（W Task 6）；这里只测外壳的开合与键盘，
 * 后端一律回空目录，会话换取也给一个固定会话。
 */
function stubBackend(): void {
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8000')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase()
      const path = new URL(String(input)).pathname
      if (method === 'POST' && path === '/api/v2/merchant/sessions') {
        return new Response(
          JSON.stringify({
            session_id: 'sid'.padEnd(43, '0'),
            role: 'MERCHANT',
            expires_at: '2099-01-01T00:00:00Z',
            merchant_display_name: 'Borough商家100',
          }),
          { status: 201, headers: { 'content-type': 'application/json' } },
        )
      }
      return new Response(JSON.stringify({ items: [], next_cursor: null, has_more: false }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }),
  )
}

function keydown(target: EventTarget, init: KeyboardEventInit): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}

beforeEach(() => {
  i18n.global.locale.value = 'zh-CN'
  homeMounts = 0
  stubBackend()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  document.body.innerHTML = ''
})

describe('MerchantShell 外壳', () => {
  it('三列：侧栏、主视图（渲染子路由）、助手栏插槽', async () => {
    const { wrapper } = await mountShell()

    expect(wrapper.find('nav').exists()).toBe(true)
    expect(wrapper.get('main#main').find('[data-testid="child"]').exists()).toBe(true)
    const rail = wrapper.get('#assistant-rail')
    expect(rail.attributes('data-state')).toBe('closed')
    wrapper.unmount()
  })

  it('助手栏默认收起，外壳标记 data-rail="closed"', async () => {
    const { wrapper } = await mountShell()

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-rail')).toBe('closed')
    wrapper.unmount()
  })

  it('有「跳到主要内容」链接', async () => {
    const { wrapper } = await mountShell()

    const skip = wrapper.get('a.skip-link')
    expect(skip.attributes('href')).toBe('#main')
    expect(skip.text()).toBe('跳到主要内容')
    wrapper.unmount()
  })

  it('左下角账号区打开偏好设置面板，再点一次关闭', async () => {
    const { wrapper } = await mountShell()
    const trigger = wrapper.get('[data-testid="preferences-trigger"]')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)

    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[role="dialog"]').text()).toContain('偏好设置')

    await trigger.trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('localStorage 抛错时外壳照常渲染，偏好面板照常可用', async () => {
    const { wrapper } = await mountShell({ brokenStorage: true })

    expect(wrapper.find('nav').exists()).toBe(true)
    await wrapper.get('[data-testid="preferences-trigger"]').trigger('click')
    await wrapper.get('select[name="size"]').setValue('lg')

    expect(document.documentElement.dataset.size).toBe('lg')
    wrapper.unmount()
  })

  it('尚未选中商家时挂载即恢复演示商家', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    const restore = vi.spyOn(auth, 'restore').mockResolvedValue(undefined)
    const router = createRouter({ history: createMemoryHistory(), routes: shellRoutes() })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(
      { template: '<RouterView />' },
      { global: { plugins: [pinia, i18n, router] } },
    )
    await flushPromises()

    expect(restore).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('切换到另一个商家时重新挂载子页面，让它用新会话重新取数', async () => {
    const { wrapper, auth } = await mountShell()
    expect(homeMounts).toBe(1)

    auth.selected = OTHER
    await flushPromises()

    expect(homeMounts).toBe(2)
    wrapper.unmount()
  })

  it('首次恢复出当前商家不算切换，子页面不重复挂载', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    vi.spyOn(auth, 'restore').mockResolvedValue(undefined)
    const router = createRouter({ history: createMemoryHistory(), routes: shellRoutes() })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(
      { template: '<RouterView />' },
      { global: { plugins: [pinia, i18n, router] } },
    )
    await flushPromises()

    auth.selected = MERCHANTS[0]
    await flushPromises()

    expect(homeMounts).toBe(1)
    wrapper.unmount()
  })

  it('窄屏打开侧栏抽屉后焦点移进抽屉', async () => {
    const { wrapper } = await mountShell()
    const menu = wrapper.get<HTMLButtonElement>('[aria-controls="side-nav"]')

    menu.element.focus()
    await menu.trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-side')).toBe('open')
    expect(wrapper.get('#side-nav').element.contains(document.activeElement)).toBe(true)
    wrapper.unmount()
  })

  it('抽屉里按 Escape 关闭抽屉，焦点回到菜单按钮', async () => {
    const { wrapper } = await mountShell()
    const menu = wrapper.get<HTMLButtonElement>('[aria-controls="side-nav"]')
    await menu.trigger('click')
    await flushPromises()

    const focused = document.activeElement as HTMLElement
    focused.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-side')).toBe('closed')
    expect(document.activeElement).toBe(menu.element)
    wrapper.unmount()
  })

  it('抽屉里偏好面板开着时，Escape 只关面板，不连带关抽屉', async () => {
    const { wrapper } = await mountShell()
    await wrapper.get('[aria-controls="side-nav"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="preferences-trigger"]').trigger('click')
    await flushPromises()

    const focused = document.activeElement as HTMLElement
    focused.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
    )
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-side')).toBe('open')
    wrapper.unmount()
  })

  it('抽屉关着时按 Escape 不做任何事', async () => {
    const { wrapper } = await mountShell()
    const before = document.activeElement

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.get('[data-testid="merchant-shell"]').attributes('data-side')).toBe('closed')
    expect(document.activeElement).toBe(before)
    wrapper.unmount()
  })
})

describe('MerchantShell 助手栏开合（W Task 6）', () => {
  function shellState(wrapper: Awaited<ReturnType<typeof mountShell>>['wrapper']) {
    return wrapper.get('[data-testid="merchant-shell"]').attributes('data-rail')
  }

  it('侧栏「运营助手」按钮切换助手栏，aria-pressed / aria-expanded 同步', async () => {
    const { wrapper } = await mountShell()
    const assist = wrapper.get('[data-nav-group="assistant"] button')
    expect(assist.attributes('aria-pressed')).toBe('false')
    expect(assist.attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('#assistant-rail').attributes('hidden')).toBeDefined()

    await assist.trigger('click')
    await flushPromises()
    expect(shellState(wrapper)).toBe('open')
    expect(assist.attributes('aria-pressed')).toBe('true')
    expect(assist.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('#assistant-rail').attributes('hidden')).toBeUndefined()

    await assist.trigger('click')
    await flushPromises()
    expect(shellState(wrapper)).toBe('closed')
    expect(assist.attributes('aria-pressed')).toBe('false')
    wrapper.unmount()
  })

  it('窄屏顶栏的「运营助手」按钮同样切换，并同步 aria 状态', async () => {
    const { wrapper } = await mountShell()
    const top = wrapper.get('.shell__assist-top')
    expect(top.attributes('aria-controls')).toBe('assistant-rail')
    expect(top.attributes('aria-expanded')).toBe('false')

    await top.trigger('click')
    await flushPromises()
    expect(shellState(wrapper)).toBe('open')
    expect(top.attributes('aria-pressed')).toBe('true')
    expect(top.attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })

  it('侧栏抽屉里点「运营助手」：收起抽屉并打开助手栏', async () => {
    const { wrapper } = await mountShell()
    await wrapper.get('[aria-controls="side-nav"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-nav-group="assistant"] button').trigger('click')
    await flushPromises()

    const shell = wrapper.get('[data-testid="merchant-shell"]')
    expect(shell.attributes('data-side')).toBe('closed')
    expect(shell.attributes('data-rail')).toBe('open')
    wrapper.unmount()
  })

  it('Ctrl + J 切换助手栏并 preventDefault（Chrome 默认会打开下载页）', async () => {
    const { wrapper } = await mountShell()

    const opening = keydown(document.body, { key: 'j', ctrlKey: true })
    await flushPromises()
    expect(opening.defaultPrevented).toBe(true)
    expect(shellState(wrapper)).toBe('open')

    const closing = keydown(document.body, { key: 'j', metaKey: true })
    await flushPromises()
    expect(closing.defaultPrevented).toBe(true)
    expect(shellState(wrapper)).toBe('closed')
    wrapper.unmount()
  })

  it('输入框聚焦时 Ctrl + J 同样生效（助手栏输入框里按下即收起）', async () => {
    const { wrapper } = await mountShell()
    useRailStore().show()
    await flushPromises()
    const input = wrapper.get<HTMLTextAreaElement>('[data-test=ops-input]').element
    input.focus()
    expect(document.activeElement).toBe(input)

    const event = keydown(input, { key: 'J', ctrlKey: true })
    await flushPromises()

    expect(event.defaultPrevented).toBe(true)
    expect(shellState(wrapper)).toBe('closed')
    wrapper.unmount()
  })

  it('页面上有模态对话框（aria-modal）时 Ctrl + J 不切换助手栏，但仍拦下浏览器默认行为', async () => {
    const { wrapper } = await mountShell()
    const modal = document.createElement('div')
    modal.setAttribute('role', 'dialog')
    modal.setAttribute('aria-modal', 'true')
    document.body.appendChild(modal)
    try {
      const blocked = keydown(document.body, { key: 'j', ctrlKey: true })
      await flushPromises()
      expect(blocked.defaultPrevented).toBe(true)
      expect(shellState(wrapper)).toBe('closed')

      modal.remove()
      keydown(document.body, { key: 'j', ctrlKey: true })
      await flushPromises()
      expect(shellState(wrapper)).toBe('open')
    } finally {
      modal.remove()
      wrapper.unmount()
    }
  })

  it('不带修饰键的 j 不切换，输入照常', async () => {
    const { wrapper } = await mountShell()

    const event = keydown(document.body, { key: 'j' })
    await flushPromises()

    expect(event.defaultPrevented).toBe(false)
    expect(shellState(wrapper)).toBe('closed')
    wrapper.unmount()
  })

  it('助手栏里按 Escape 收起，焦点回到打开它的按钮', async () => {
    const { wrapper } = await mountShell()
    const assist = wrapper.get<HTMLButtonElement>('[data-nav-group="assistant"] button')
    assist.element.focus()
    await assist.trigger('click')
    await flushPromises()
    const input = wrapper.get<HTMLTextAreaElement>('[data-test=ops-input]').element
    expect(document.activeElement).toBe(input)

    const event = keydown(input, { key: 'Escape' })
    await flushPromises()

    expect(event.defaultPrevented).toBe(true)
    expect(shellState(wrapper)).toBe('closed')
    expect(document.activeElement).toBe(assist.element)
    wrapper.unmount()
  })

  function viewport(narrow: boolean): void {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) => ({ matches: narrow, media: query }) as MediaQueryList,
    )
  }

  it('宽屏下焦点不在助手栏里时 Escape 不收起助手栏（留给页面自己的弹层）', async () => {
    viewport(false)
    const { wrapper } = await mountShell()
    useRailStore().show()
    await flushPromises()
    ;(document.activeElement as HTMLElement | null)?.blur()

    keydown(document.body, { key: 'Escape' })
    await flushPromises()

    expect(shellState(wrapper)).toBe('open')
    wrapper.unmount()
  })

  it('1100px 以下（抽屉）焦点在哪都能用 Escape 收起', async () => {
    viewport(true)
    const { wrapper } = await mountShell()
    useRailStore().show()
    await flushPromises()
    ;(document.activeElement as HTMLElement | null)?.blur()

    const event = keydown(document.body, { key: 'Escape' })
    await flushPromises()

    expect(event.defaultPrevented).toBe(true)
    expect(shellState(wrapper)).toBe('closed')
    wrapper.unmount()
  })

  it('页面弹层已处理的 Escape（defaultPrevented）不收起助手栏', async () => {
    viewport(true)
    const { wrapper } = await mountShell()
    useRailStore().show()
    await flushPromises()
    const input = wrapper.get<HTMLTextAreaElement>('[data-test=ops-input]').element
    input.addEventListener('keydown', (event) => event.preventDefault(), { once: true })

    keydown(input, { key: 'Escape' })
    await flushPromises()

    expect(shellState(wrapper)).toBe('open')
    wrapper.unmount()
  })

  it('窄屏抽屉带遮罩：助手栏打开时出现遮罩，点遮罩收起', async () => {
    const { wrapper } = await mountShell()
    expect(wrapper.find('[data-testid="rail-backdrop"]').exists()).toBe(false)

    useRailStore().show()
    await flushPromises()
    const backdrop = wrapper.get('[data-testid="rail-backdrop"]')
    expect(backdrop.attributes('aria-label')).toBe('收起助手')

    await backdrop.trigger('click')
    await flushPromises()
    expect(shellState(wrapper)).toBe('closed')
    expect(wrapper.find('[data-testid="rail-backdrop"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('换页不收起助手栏（常驻外壳）', async () => {
    const { wrapper, router } = await mountShell()
    useRailStore().show()
    await flushPromises()

    await router.push('/inventory')
    await flushPromises()

    expect(shellState(wrapper)).toBe('open')
    wrapper.unmount()
  })
})
