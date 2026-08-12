import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DetailTable from './DetailTable.vue'

const data = {
  rows: [
    { order_no: 'BR20260803-0001', paid_amount: '258.00', custom_field: null },
    { order_no: 'BR20260803-0002', paid_amount: '129.50', custom_field: '保留原名' },
  ],
  totalRows: 1284,
  truncated: true,
}

describe('DetailTable', () => {
  it('保留表格语义、未知列名和截断说明', () => {
    const wrapper = mount(DetailTable, { props: { data, apiBaseUrl: 'https://api.example.test' } })

    expect(wrapper.get('caption').text()).toContain('经营明细')
    expect(wrapper.findAll('th[scope="col"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('custom_field')
    expect(wrapper.text()).toContain('共 1284 行，已展示前 2 行')
  })

  it('只为尚未过期的签名导出链接输出安全的原生下载入口', () => {
    const wrapper = mount(DetailTable, {
      props: {
        data,
        apiBaseUrl: 'https://api.example.test',
        now: new Date('2026-08-08T00:00:00Z'),
        exportInfo: {
          id: 'export-1',
          url: '/api/exports/export-1?signature=abc',
          expiresAt: '2026-08-08T00:15:00Z',
        },
      },
    })

    const link = wrapper.get('[data-testid="download-export"]')
    expect(link.attributes('href')).toBe(
      'https://api.example.test/api/exports/export-1?signature=abc',
    )
    expect(link.attributes('download')).toBeDefined()
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener')
  })

  it('未提供 apiBaseUrl 且全局配置缺失时不崩溃，只是不出现下载链接', () => {
    // 不传 apiBaseUrl 时组件会退回 resolveApiBaseUrl()，测试环境没有配置
    // VITE_API_BASE_URL，这里要确认组件优雅降级而不是在 computed 里抛出
    // 未捕获的 ApiConfigError 把整条消息的渲染带崩。
    const wrapper = mount(DetailTable, {
      props: {
        data,
        now: new Date('2026-08-08T00:00:00Z'),
        exportInfo: {
          id: 'export-1',
          url: '/api/exports/export-1?signature=abc',
          expiresAt: '2026-08-08T00:15:00Z',
        },
      },
    })

    expect(wrapper.find('[data-testid="download-export"]').exists()).toBe(false)
    expect(wrapper.get('caption').text()).toContain('经营明细')
  })

  it('在链接过期时禁用下载而不发出无效请求', () => {
    const wrapper = mount(DetailTable, {
      props: {
        data,
        apiBaseUrl: 'https://api.example.test',
        now: new Date('2026-08-08T00:00:00Z'),
        exportInfo: {
          id: 'export-1',
          url: '/api/exports/export-1?signature=abc',
          expiresAt: '2026-08-08T00:00:20Z',
        },
      },
    })

    expect(wrapper.find('[data-testid="download-export"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('下载链接已过期')
  })
})
