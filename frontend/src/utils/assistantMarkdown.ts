/**
 * 助手回答的受控 Markdown 子集解析。
 *
 * 模型回答常带 Markdown 表格、列表和加粗；助手栏原先按纯文本显示，表格会露出 `|---|`。
 * 这里只把文本拆成**结构**（段落、标题、列表、表格、分隔线，行内只有加粗与行内代码），
 * 渲染由 `AssistantMarkdown.vue` 用模板文本插值完成——全程不产出 HTML 字符串、不用 `v-html`，
 * 所以回答里的 `<script>`、`<img onerror>` 只会原样显示成文字，不需要另做 XSS 过滤。
 *
 * 子集之外的语法（链接、图片、引用、嵌套列表、HTML）一律按普通文字保留，不猜测含义。
 * 流式输出时表格的分隔行未到之前，表头按普通段落显示，分隔行到达后自动变成表格。
 */

export type InlineSegment =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; text: string }
  | { kind: 'code'; text: string }

export type CellAlign = 'left' | 'center' | 'right' | null

export type MarkdownBlock =
  | { kind: 'paragraph'; lines: InlineSegment[][] }
  | { kind: 'heading'; segments: InlineSegment[] }
  | { kind: 'list'; ordered: boolean; start: number; items: InlineSegment[][] }
  | { kind: 'table'; header: InlineSegment[][]; align: CellAlign[]; rows: InlineSegment[][][] }
  | { kind: 'rule' }

const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/
const BULLET = /^\s{0,3}[-*+]\s+(.*)$/
const ORDERED = /^\s{0,3}(\d{1,9})[.)]\s+(.*)$/
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/
const SEPARATOR_CELL = /^:?-+:?$/
const NUMERIC_CELL = /^[-+]?[¥$€£]?\d[\d,]*(\.\d+)?\s*(%|元|件|天|笔|单|个)?$/
const INLINE = /(`[^`\n]+`|\*\*[^*\n]+?\*\*)/g

export function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = []
  let last = 0
  for (const match of text.matchAll(INLINE)) {
    const token = match[0]
    const index = match.index ?? 0
    if (index > last) segments.push({ kind: 'text', text: text.slice(last, index) })
    segments.push(
      token.startsWith('`')
        ? { kind: 'code', text: token.slice(1, -1) }
        : { kind: 'strong', text: token.slice(2, -2) },
    )
    last = index + token.length
  }
  if (last < text.length) segments.push({ kind: 'text', text: text.slice(last) })
  return segments
}

/** 按未转义的 `|` 切分一行表格；首尾的竖线可有可无。 */
export function splitRow(line: string): string[] {
  let body = line.trim()
  if (body.startsWith('|')) body = body.slice(1)
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1)
  const cells: string[] = []
  let current = ''
  for (let i = 0; i < body.length; i += 1) {
    const char = body[i]
    if (char === '\\' && body[i + 1] === '|') {
      current += '|'
      i += 1
    } else if (char === '|') {
      cells.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }
  cells.push(current.trim())
  return cells
}

function separatorAlign(line: string, columns: number): CellAlign[] | null {
  if (!line.includes('-')) return null
  const cells = splitRow(line)
  if (cells.length !== columns || !cells.every((cell) => SEPARATOR_CELL.test(cell))) return null
  return cells.map((cell) => {
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    if (left && right) return 'center'
    if (right) return 'right'
    if (left) return 'left'
    return null
  })
}

function isTableRow(line: string): boolean {
  return line.includes('|') && line.trim() !== ''
}

/** 分隔行没写对齐时，整列都是数字就右对齐，方便对位比较。 */
function autoAlign(align: CellAlign[], rows: string[][]): CellAlign[] {
  return align.map((value, column) => {
    if (value !== null) return value
    const cells = rows.map((row) => row[column] ?? '').filter((cell) => cell !== '')
    return cells.length > 0 && cells.every((cell) => NUMERIC_CELL.test(cell)) ? 'right' : null
  })
}

/** 表格每行按表头列数补齐或截断（与 GFM 一致），避免错列。 */
function fitRow(cells: string[], columns: number): string[] {
  const fitted = cells.slice(0, columns)
  while (fitted.length < columns) fitted.push('')
  return fitted
}

export function parseAssistantMarkdown(source: string): MarkdownBlock[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let paragraph: InlineSegment[][] = []

  const flushParagraph = (): void => {
    if (paragraph.length > 0) blocks.push({ kind: 'paragraph', lines: paragraph })
    paragraph = []
  }

  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    if (line.trim() === '') {
      flushParagraph()
      i += 1
      continue
    }

    if (isTableRow(line) && i + 1 < lines.length) {
      const headerCells = splitRow(line)
      const align = separatorAlign(lines[i + 1], headerCells.length)
      if (align !== null) {
        flushParagraph()
        const rows: string[][] = []
        i += 2
        while (i < lines.length && isTableRow(lines[i])) {
          rows.push(fitRow(splitRow(lines[i]), headerCells.length))
          i += 1
        }
        blocks.push({
          kind: 'table',
          header: headerCells.map(parseInline),
          align: autoAlign(align, rows),
          rows: rows.map((row) => row.map(parseInline)),
        })
        continue
      }
    }

    if (RULE.test(line)) {
      flushParagraph()
      blocks.push({ kind: 'rule' })
      i += 1
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      flushParagraph()
      blocks.push({ kind: 'heading', segments: parseInline(heading[1]) })
      i += 1
      continue
    }

    const bullet = BULLET.exec(line)
    const ordered = bullet ? null : ORDERED.exec(line)
    if (bullet || ordered) {
      flushParagraph()
      const isOrdered = ordered !== null
      const pattern = isOrdered ? ORDERED : BULLET
      const items: InlineSegment[][] = []
      const start = isOrdered ? Number(ordered[1]) : 1
      while (i < lines.length) {
        const item = pattern.exec(lines[i])
        if (!item) break
        items.push(parseInline(isOrdered ? item[2] : item[1]))
        i += 1
      }
      blocks.push({ kind: 'list', ordered: isOrdered, start, items })
      continue
    }

    paragraph.push(parseInline(line))
    i += 1
  }
  flushParagraph()
  return blocks
}
