import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'
import { AppError } from '@/api/errors'
import { setChatTransport } from '@/api/transport'
import { i18n, type SupportedLocale } from '@/i18n'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useLocaleStore } from '@/stores/locale'

import KnowledgeBaseView from './KnowledgeBaseView.vue'

const DEFAULT_ROOTS: KnowledgeTreeNode[] = [
  {
    name: 'index',
    path: 'index',
    nodeType: 'directory',
    readOnly: false,
    size: 0,
    version: 'idx-v1',
    children: [],
  },
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
        children: [
          {
            name: '业务流程',
            path: '业务/客服/业务流程',
            nodeType: 'directory',
            readOnly: false,
            size: 0,
            version: 'section-v1',
            children: [],
          },
        ],
      },
    ],
  },
]

/**
 * 传输层收到的是契约里的 snake_case 原始载荷，`getKnowledgeTree` 会再跑一遍
 * Adapter 转成 camelCase——测试用的 `KnowledgeTreeNode[]` fixture 本身已经是
 * Adapter 转换后的形状，喂给 mock transport 前要转回 snake_case，否则
 * `node_type`/`read_only` 读到 undefined，所有节点判定都会失真。
 */
function toWireNode(node: KnowledgeTreeNode): Record<string, unknown> {
  return {
    name: node.name,
    path: node.path,
    node_type: node.nodeType,
    read_only: node.readOnly,
    size: node.size,
    version: node.version,
    children: node.children.map(toWireNode),
  }
}

function treeResponse(roots: KnowledgeTreeNode[]): Response {
  return Response.json({ roots: roots.map(toWireNode) })
}

async function mountAuthorized(
  roots: KnowledgeTreeNode[] = DEFAULT_ROOTS,
  locale: SupportedLocale = 'zh-CN',
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useKnowledgeStore()
  store.setAdminToken('admin-token')
  useLocaleStore().setLocale(locale)
  // 页面挂载时的 onMounted 会自动重新拉取目录树；这里让它返回与手工种入的
  // roots 一致的数据，避免它把测试手工设置的选中状态覆盖成空目录。
  setChatTransport(async () => treeResponse(roots))
  const wrapper = mount(KnowledgeBaseView, { global: { plugins: [pinia, i18n] } })
  await flushPromises()
  return { wrapper, store }
}

describe('KnowledgeBaseView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('zh-CN')
  })

  afterEach(() => {
    setChatTransport(undefined)
  })

  it('未授权时也能看到并使用统一语言切换器，不必先输入令牌才能切换语言（Finding 4）', async () => {
    const wrapper = mount(KnowledgeBaseView, { global: { plugins: [createPinia(), i18n] } })

    // 未授权、只展示令牌对话框时也要能摸到语言切换器——直接落地在
    // /knowledge-base 的用户（例如收藏的管理链接）在输入令牌之前也应该能
    // 切换语言。之前它只在 v-else（授权后）分支里渲染，pre-auth 页面完全
    // 够不到它。
    const switcher = wrapper.find('[data-testid="language-switcher"]')
    expect(switcher.exists()).toBe(true)
    expect(wrapper.get('h1').text()).toBe('知识库维护后台')

    // 不只是渲染出来——点击真的要生效：验证它确实驱动了 localeStore 并让
    // 令牌对话框本身重新按新语言渲染。
    await switcher.trigger('click')

    expect(wrapper.get('h1').text()).toBe('Knowledge base administration')
  })

  it('无效管理员令牌后保留输入入口，允许直接重试', async () => {
    setChatTransport(async () => {
      throw new AppError('AUTH_REQUIRED', '管理员令牌无效', { status: 401 })
    })
    const wrapper = mount(KnowledgeBaseView, { global: { plugins: [createPinia(), i18n] } })

    await wrapper.get('input').setValue('bad-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('input').exists()).toBe(true)
    expect(wrapper.text()).toContain('管理员令牌无效')
  })

  it('选中固定板块目录时新建文档按钮可用，选中业务域根目录时不可用', async () => {
    const { wrapper } = await mountAuthorized()

    await wrapper.get('[data-path="业务/客服/业务流程"]').trigger('click')
    expect(wrapper.get('[data-testid="create-document"]').attributes('disabled')).toBeUndefined()

    await wrapper.get('[data-path="业务/客服"]').trigger('click')
    expect(wrapper.get('[data-testid="create-document"]').attributes('disabled')).toBeDefined()
  })

  it('选中业务域根目录时重命名与删除按钮可用', async () => {
    const { wrapper } = await mountAuthorized()

    await wrapper.get('[data-path="业务/客服"]').trigger('click')

    expect(wrapper.get('[data-testid="rename-domain"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="delete-node"]').attributes('disabled')).toBeUndefined()
  })

  it('点击新建业务域、填写名称提交后调用后端并刷新目录树', async () => {
    const { wrapper } = await mountAuthorized()
    const requests: string[] = []
    setChatTransport(async (request) => {
      requests.push(`${request.method} ${request.path}`)
      if (request.method === 'POST') {
        return Response.json(
          {
            name: '售后',
            path: '业务/售后',
            node_type: 'directory',
            read_only: false,
            size: 0,
            version: 'v1',
            children: [],
          },
          { status: 201 },
        )
      }
      return treeResponse(DEFAULT_ROOTS)
    })

    await wrapper.get('[data-testid="create-domain"]').trigger('click')
    await wrapper.get('input').setValue('售后')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(requests).toContain('POST /api/admin/knowledge/business-domains')
    expect(wrapper.find('.prompt-dialog-backdrop').exists()).toBe(false)
  })

  it('新建业务域失败时对话框展示错误并保持打开', async () => {
    const { wrapper } = await mountAuthorized()
    setChatTransport(async () => {
      throw new AppError('WIKI_NODE_EXISTS', '同名业务域已存在', { status: 409 })
    })

    await wrapper.get('[data-testid="create-domain"]').trigger('click')
    await wrapper.get('input').setValue('客服')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('.prompt-dialog-backdrop').exists()).toBe(true)
    expect(wrapper.text()).toContain('同名业务域已存在')
  })

  it('删除文档需二次确认，确认后调用删除接口并清空选中', async () => {
    const documentRoots: KnowledgeTreeNode[] = [
      {
        name: 'index',
        path: 'index',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'idx-v1',
        children: [
          {
            name: '运营手册.md',
            path: 'index/运营手册.md',
            nodeType: 'document',
            readOnly: false,
            size: 1,
            version: 'doc-v1',
            children: [],
          },
        ],
      },
    ]
    const { wrapper } = await mountAuthorized(documentRoots)
    setChatTransport(async (request) => {
      if (request.method === 'GET' && request.path.includes('/documents/')) {
        return Response.json({
          path: 'index/运营手册.md',
          content: '正文',
          read_only: false,
          version: 'doc-v1',
        })
      }
      if (request.method === 'DELETE') return new Response(null, { status: 204 })
      return Response.json({ roots: [] })
    })

    await wrapper.get('[data-path="index/运营手册.md"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="delete-node"]').trigger('click')

    expect(wrapper.text()).toContain('运营手册.md')
    await wrapper.get('[data-testid="confirm"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-delete-backdrop').exists()).toBe(false)
  })
})

describe('KnowledgeBaseView en-US 下确定性文案为英文', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useLocaleStore().setLocale('zh-CN')
  })

  it('顶栏标题、退出按钮、工具栏按钮与空态提示均为英文，并插入统一语言切换器', async () => {
    const { wrapper } = await mountAuthorized(DEFAULT_ROOTS, 'en-US')

    expect(wrapper.get('h1').text()).toBe('Knowledge base administration')
    expect(wrapper.text()).toContain('Sign out')
    expect(wrapper.get('[data-testid="create-document"]').text()).toBe('New document')
    expect(wrapper.get('[data-testid="rename-domain"]').text()).toBe('Rename business domain')
    expect(wrapper.get('[data-testid="delete-node"]').text()).toBe('Delete')
    expect(wrapper.text()).toContain('Select a document to maintain.')
    expect(wrapper.find('[data-testid="language-switcher"]').exists()).toBe(true)
  })

  it('新建文档对话框标题、标签与占位提示均为英文', async () => {
    const { wrapper } = await mountAuthorized(DEFAULT_ROOTS, 'en-US')

    await wrapper.get('[data-path="业务/客服/业务流程"]').trigger('click')
    await wrapper.get('[data-testid="create-document"]').trigger('click')

    expect(wrapper.get('h2').text()).toBe('New document')
    expect(wrapper.text()).toContain('Document name')
    expect(wrapper.get('input').attributes('placeholder')).toBe(
      'e.g. order-fulfillment-definition.md',
    )
  })

  it('新建业务域失败时英文对话框展示后端返回的错误信息', async () => {
    const { wrapper } = await mountAuthorized(DEFAULT_ROOTS, 'en-US')
    setChatTransport(async () => {
      throw new AppError('WIKI_NODE_EXISTS', 'A business domain with this name already exists', {
        status: 409,
      })
    })

    await wrapper.get('[data-testid="create-domain"]').trigger('click')
    expect(wrapper.get('h2').text()).toBe('New business domain')
    await wrapper.get('input').setValue('CustomerService')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('A business domain with this name already exists')
  })

  it('删除确认对话框标题、路径与按钮均为英文', async () => {
    const { wrapper } = await mountAuthorized(DEFAULT_ROOTS, 'en-US')

    await wrapper.get('[data-path="业务/客服"]').trigger('click')
    await wrapper.get('[data-testid="delete-node"]').trigger('click')

    expect(wrapper.get('h2').text()).toBe('Delete knowledge node')
    expect(wrapper.text()).toContain('业务/客服')
    expect(wrapper.get('[data-testid="cancel"]').text()).toBe('Cancel')
  })

  it('文档保存冲突（412）时编辑器展示英文提示，且加载态与选择文档提示均为英文', async () => {
    const documentRoots: KnowledgeTreeNode[] = [
      {
        name: 'index',
        path: 'index',
        nodeType: 'directory',
        readOnly: false,
        size: 0,
        version: 'idx-v1',
        children: [
          {
            name: 'runbook.md',
            path: 'index/runbook.md',
            nodeType: 'document',
            readOnly: false,
            size: 1,
            version: 'doc-v1',
            children: [],
          },
        ],
      },
    ]
    const { wrapper } = await mountAuthorized(documentRoots, 'en-US')

    expect(wrapper.text()).toContain('Select a document to maintain.')

    setChatTransport(async (request) => {
      if (request.method === 'GET' && request.path.includes('/documents/')) {
        return Response.json({
          path: 'index/runbook.md',
          content: 'source text',
          read_only: false,
          version: 'doc-v1',
        })
      }
      if (request.method === 'PUT') {
        throw new AppError('WIKI_VERSION_CONFLICT', 'Conflict', { status: 412 })
      }
      return Response.json({ roots: [] })
    })

    await wrapper.get('[data-path="index/runbook.md"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="save"]').text()).toBe('Save changes')

    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('This document was modified by another maintainer')
  })

  it('非 Error 异常时展示英文兜底文案，不泄露非预期抛出值', async () => {
    setChatTransport(async () => {
      throw 'boom'
    })
    const wrapper = mount(KnowledgeBaseView, { global: { plugins: [createPinia(), i18n] } })
    useLocaleStore().setLocale('en-US')

    await wrapper.get('input').setValue('bad-token')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Admin token verification failed.')
  })
})
