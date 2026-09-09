import { describe, expect, it } from 'vitest'

import type { KnowledgeTreeNode } from '@/api/adapters/knowledge'

import {
  canDeleteNode,
  displayNodeName,
  findNode,
  isBusinessDomain,
  isDocumentParent,
} from './knowledgeTree'

function directory(
  path: string,
  readOnly = false,
  children: KnowledgeTreeNode[] = [],
): KnowledgeTreeNode {
  return {
    name: path.split('/').at(-1) ?? path,
    path,
    nodeType: 'directory',
    readOnly,
    size: 0,
    version: 'v1',
    children,
  }
}

function document(path: string, readOnly = false): KnowledgeTreeNode {
  return {
    name: path.split('/').at(-1) ?? path,
    path,
    nodeType: 'document',
    readOnly,
    size: 1,
    version: 'v1',
    children: [],
  }
}

describe('isBusinessDomain', () => {
  it('业务域根目录（业务/客服）判定为业务域', () => {
    expect(isBusinessDomain(directory('业务/客服'))).toBe(true)
  })

  it('业务根目录本身（业务）不是业务域', () => {
    expect(isBusinessDomain(directory('业务'))).toBe(false)
  })

  it('业务域下的固定板块（业务/客服/业务流程）不是业务域', () => {
    expect(isBusinessDomain(directory('业务/客服/业务流程'))).toBe(false)
  })

  it('只读目录不是可管理的业务域', () => {
    expect(isBusinessDomain(directory('业务/客服', true))).toBe(false)
  })
})

describe('isDocumentParent', () => {
  it('index 根目录可以新建文档', () => {
    expect(isDocumentParent(directory('index'))).toBe(true)
  })

  it('业务域下的固定板块可以新建文档', () => {
    expect(isDocumentParent(directory('业务/客服/业务流程'))).toBe(true)
  })

  it('业务域根目录本身不能直接新建文档', () => {
    expect(isDocumentParent(directory('业务/客服'))).toBe(false)
  })

  it('非固定板块名称不能新建文档', () => {
    expect(isDocumentParent(directory('业务/客服/随便起的目录'))).toBe(false)
  })
})

describe('canDeleteNode', () => {
  it('可维护文档可以删除', () => {
    expect(canDeleteNode(document('index/运营手册.md'))).toBe(true)
  })

  it('业务域可以删除', () => {
    expect(canDeleteNode(directory('业务/客服'))).toBe(true)
  })

  it('固定板块目录本身不能删除', () => {
    expect(canDeleteNode(directory('业务/客服/业务流程'))).toBe(false)
  })

  it('只读记忆文档不能删除', () => {
    expect(canDeleteNode(document('memory/merchants/a/TRADE.md', true))).toBe(false)
  })
})

describe('displayNodeName', () => {
  it('中文模式下始终原样返回 name', () => {
    expect(displayNodeName(directory('业务'), 'zh-CN')).toBe('业务')
    expect(displayNodeName(directory('业务/客服/业务流程'), 'zh-CN')).toBe('业务流程')
  })

  it('英语模式下业务根目录展示为 Business，稳定 path 不变', () => {
    const node = directory('业务')
    expect(displayNodeName(node, 'en-US')).toBe('Business')
    expect(node.path).toBe('业务')
  })

  it('英语模式下已知 shipped 业务域展示英文名，未知业务域原样展示', () => {
    expect(displayNodeName(directory('业务/客服工单'), 'en-US')).toBe('Customer service tickets')
    const unknown = directory('业务/随便起的域')
    expect(displayNodeName(unknown, 'en-US')).toBe('随便起的域')
  })

  it('英语模式下固定板块展示英文名，稳定 path 与匹配逻辑不受影响', () => {
    const section = directory('业务/客服工单/业务流程')
    expect(displayNodeName(section, 'en-US')).toBe('Business process')
    expect(isDocumentParent(section)).toBe(true)
    expect(section.path).toBe('业务/客服工单/业务流程')
  })

  it('英语模式下文档文件名等自由内容原样展示', () => {
    expect(displayNodeName(document('index/运营手册.md'), 'en-US')).toBe('运营手册.md')
  })
})

describe('findNode', () => {
  it('在嵌套目录树中按路径找到节点', () => {
    const roots = [
      directory('业务', false, [
        directory('业务/客服', false, [document('业务/客服/业务流程/x.md')]),
      ]),
    ]

    expect(findNode(roots, '业务/客服/业务流程/x.md')?.path).toBe('业务/客服/业务流程/x.md')
  })

  it('路径不存在时返回 undefined', () => {
    expect(findNode([directory('index')], '不存在')).toBeUndefined()
  })
})
