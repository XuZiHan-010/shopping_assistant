import { describe, expect, it } from 'vitest'

import { parseAssistantMarkdown, parseInline, splitRow } from './assistantMarkdown'

const ALERT_ANSWER = [
  '当前只有 1 条低库存告警：',
  '',
  '| 商品 | 在库 | 占用 | 可售 | 低库存阈值 | 近 30 天销量 | 预计可售天数 |',
  '|---|---|---|---|---|---|---|',
  '| 粗陶手作咖啡杯（两只装） | 3 | 0 | 3 | 5 | 25 | 3 天 |',
  '',
  '补货数量由你决定。',
].join('\n')

describe('parseAssistantMarkdown', () => {
  it('把截图里的告警回答拆成段落、表格、段落', () => {
    const blocks = parseAssistantMarkdown(ALERT_ANSWER)

    expect(blocks.map((block) => block.kind)).toEqual(['paragraph', 'table', 'paragraph'])
    const table = blocks[1]
    if (table.kind !== 'table') throw new Error('expected table')
    expect(table.header).toHaveLength(7)
    expect(table.rows).toHaveLength(1)
    expect(table.rows[0][0]).toEqual([{ kind: 'text', text: '粗陶手作咖啡杯（两只装）' }])
    // 数字列自动右对齐，文字列不设对齐。
    expect(table.align).toEqual([null, 'right', 'right', 'right', 'right', 'right', 'right'])
  })

  it('分隔行写了对齐时按它来', () => {
    const [table] = parseAssistantMarkdown('| a | b | c |\n|:--|:-:|--:|\n| x | y | z |')
    if (table.kind !== 'table') throw new Error('expected table')
    expect(table.align).toEqual(['left', 'center', 'right'])
  })

  it('行列数不齐时按表头补齐或截断', () => {
    const [table] = parseAssistantMarkdown('| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |')
    if (table.kind !== 'table') throw new Error('expected table')
    expect(table.rows.map((row) => row.length)).toEqual([2, 2])
  })

  it('流式输出中分隔行未到时，表头先按段落显示', () => {
    const blocks = parseAssistantMarkdown('| 商品 | 在库 |')
    expect(blocks.map((block) => block.kind)).toEqual(['paragraph'])
  })

  it('分隔行列数与表头不符时不当作表格', () => {
    const blocks = parseAssistantMarkdown('| a | b |\n|---|\n| 1 | 2 |')
    expect(blocks.every((block) => block.kind === 'paragraph')).toBe(true)
  })

  it('识别无序列表、有序列表（保留起始序号）、标题与分隔线', () => {
    const blocks = parseAssistantMarkdown('## 结论\n- 甲\n- 乙\n\n3. 丙\n4. 丁\n\n---\n收尾')
    expect(blocks.map((block) => block.kind)).toEqual([
      'heading',
      'list',
      'list',
      'rule',
      'paragraph',
    ])
    const ordered = blocks[2]
    if (ordered.kind !== 'list') throw new Error('expected list')
    expect(ordered.ordered).toBe(true)
    expect(ordered.start).toBe(3)
    expect(ordered.items).toHaveLength(2)
  })

  it('同一段落内的换行保留为多行', () => {
    const [paragraph] = parseAssistantMarkdown('第一行\n第二行')
    if (paragraph.kind !== 'paragraph') throw new Error('expected paragraph')
    expect(paragraph.lines).toHaveLength(2)
  })

  it('统一处理 CRLF 换行', () => {
    const blocks = parseAssistantMarkdown('| a |\r\n|---|\r\n| 1 |')
    expect(blocks.map((block) => block.kind)).toEqual(['table'])
  })
})

describe('parseInline', () => {
  it('切出加粗与行内代码，其余保持文字', () => {
    expect(parseInline('需要你在**审批界面**批准，工具 `draft_restock`。')).toEqual([
      { kind: 'text', text: '需要你在' },
      { kind: 'strong', text: '审批界面' },
      { kind: 'text', text: '批准，工具 ' },
      { kind: 'code', text: 'draft_restock' },
      { kind: 'text', text: '。' },
    ])
  })

  it('HTML 只是文字片段', () => {
    expect(parseInline('<img src=x onerror=alert(1)>')).toEqual([
      { kind: 'text', text: '<img src=x onerror=alert(1)>' },
    ])
  })
})

describe('splitRow', () => {
  it('支持转义竖线，首尾竖线可省', () => {
    expect(splitRow('| a \\| b | c |')).toEqual(['a | b', 'c'])
    expect(splitRow('a | b')).toEqual(['a', 'b'])
  })
})
