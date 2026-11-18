import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AssistantMarkdown from './AssistantMarkdown.vue'

describe('AssistantMarkdown', () => {
  it('Markdown 表格渲染成真正的表格，不露出分隔行', () => {
    const wrapper = mount(AssistantMarkdown, {
      props: {
        text: '告警如下：\n\n| 商品 | 可售 |\n|---|---|\n| 粗陶手作咖啡杯 | 3 |',
      },
    })

    const table = wrapper.get('table')
    expect(table.findAll('th').map((cell) => cell.text())).toEqual(['商品', '可售'])
    expect(table.findAll('td').map((cell) => cell.text())).toEqual(['粗陶手作咖啡杯', '3'])
    expect(wrapper.text()).not.toContain('|---|')
    expect(wrapper.get('td:last-child').attributes('style')).toContain('text-align: right')
  })

  it('加粗、行内代码与列表按元素渲染', () => {
    const wrapper = mount(AssistantMarkdown, {
      props: { text: '请到**审批界面**确认 `draft_restock`\n\n- 甲\n- 乙' },
    })

    expect(wrapper.get('strong').text()).toBe('审批界面')
    expect(wrapper.get('code').text()).toBe('draft_restock')
    expect(wrapper.findAll('ul li').map((item) => item.text())).toEqual(['甲', '乙'])
  })

  it('回答里的 HTML 只作为文字显示，不生成元素', () => {
    const payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
    const wrapper = mount(AssistantMarkdown, {
      props: { text: `${payload}\n\n| a |\n|---|\n| <b>x</b> |` },
    })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('b').exists()).toBe(false)
    expect(wrapper.text()).toContain(payload)
    expect(wrapper.get('td').text()).toBe('<b>x</b>')
  })

  it('文本更新（流式片段到达）后重新解析', async () => {
    const wrapper = mount(AssistantMarkdown, { props: { text: '| a | b |' } })
    expect(wrapper.find('table').exists()).toBe(false)

    await wrapper.setProps({ text: '| a | b |\n|---|---|\n| 1 | 2 |' })
    expect(wrapper.find('table').exists()).toBe(true)
  })
})
