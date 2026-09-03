import type { AppErrorCode } from '@/api/errors'

/**
 * 中文消息目录——类型事实源。`en-US.ts` 必须满足与本文件完全相同的 key
 * 形状（见该文件的 `satisfies MessageSchema`），`keys.ts` 从本文件派生
 * `MessageSchema` 类型。新增文案先加在这里，再补齐英文版本。
 *
 * `errorCopy` 子树额外用 `satisfies Record<AppErrorCode, ...>` 约束——
 * 后端在 `AppErrorCode` 新增错误码时，这里会在 typecheck 阶段直接报错，
 * 不会有新码悄悄漏掉文案（这条防线原来在 `utils/errorCopy.ts` 里，随文案
 * 一起搬过来）。`surface`/`action` 是行为分支用的协议枚举，不是给用户看的
 * 文案，因此不进这里，仍留在 `errorCopy.ts`。
 */
export const zhCN = {
  appMeta: {
    title: 'Borough 商家 AI 助手',
  },
  languageSwitcher: {
    switchToChinese: '切换到中文',
    switchToEnglish: '切换到英文',
    chinese: '中文',
    english: '英文',
  },
  appError: {
    close: '关闭',
  },
  conversationDrawer: {
    dialogLabel: '历史会话',
    title: '历史会话',
    closeAria: '关闭历史会话',
    deleteFailed: '删除失败，请稍后重试。',
    empty: '暂无历史会话。提问之后，这里会列出可以回看的会话。',
    confirmDeleteAria: '确认删除会话 {title}',
    confirmDelete: '确认删除',
    cancelDeleteAria: '取消删除',
    cancelDelete: '取消',
    deleteAria: '删除会话 {title}',
  },
  merchantSwitcher: {
    triggerAria: '切换当前演示商家',
    listAria: '演示商家',
  },
  errorCopy: {
    // —— 后端 ErrorCode（28 项） ——
    AUTH_REQUIRED: {
      title: '登录状态已失效',
      detail: '请重新选择商家登录后再试。',
    },
    MERCHANT_SCOPE_VIOLATION: {
      title: '无权访问该商家的数据',
      detail: '当前登录身份没有权限查看这份数据，请确认选择的商家是否正确。',
    },
    NOT_FOUND: {
      title: '未找到对应内容',
      detail: '你要查看的内容可能已被删除，或者链接有误。',
    },
    METHOD_NOT_ALLOWED: {
      title: '请求方式不受支持',
      detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    },
    INVALID_REQUEST: {
      title: '请求内容有误',
      detail: '请检查输入内容后重新提交。',
    },
    IDEMPOTENCY_KEY_REUSED: {
      title: '请求被判定为重复提交',
      detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    },
    REQUEST_IN_PROGRESS: {
      title: '上一条请求仍在处理',
      detail: '请等待当前回答完成后，再发送新的问题。',
    },
    /**
     * `POST /api/admin/reports/daily/recompute` 专属，该端点没有前端消费者
     * （`docs/specs/2026-08-24-daily-report-recompute-contract.md`）。这里只是
     * 为了让 `errorCopy` 保持穷尽，不会被任何 UI 路径触发。
     */
    DAILY_REPORT_FEEDBACK_CONFLICT: {
      title: '该日报已有反馈，无法重算',
      detail: '这是应用自身的问题，已自动记录，请联系管理员处理。',
    },
    DATA_SOURCE_UNAVAILABLE: {
      title: '经营数据暂时无法访问',
      detail: '数据查询服务暂不可用，请稍后重试。',
    },
    EXPORT_LINK_EXPIRED: {
      title: '导出链接已过期',
      detail: '请重新提问，系统会为你生成新的导出链接。',
    },
    RATE_LIMITED: {
      title: '请求过于频繁',
      detail: '请稍等片刻后再试。',
    },
    LLM_BUDGET_EXCEEDED: {
      title: '今日智能问答额度已用完',
      detail: '为控制成本，AI 问答的当日额度已达上限，请明天再来，或联系客服提升额度。',
    },
    FORBIDDEN: {
      title: '没有权限执行该操作',
      detail: '当前账号没有权限执行这个操作，如需继续请联系管理员。',
    },
    HTTP_ERROR: {
      title: '请求失败',
      detail: '服务暂时出现问题，请稍后重试；如果持续出现，请联系支持。',
    },
    INTERNAL_ERROR: {
      title: '服务器出现内部错误',
      detail: '我们已记录这个问题，请稍后重试；如果持续出现，请联系支持。',
    },
    INVALID_WIKI_PATH: {
      title: '知识库路径不合法',
      detail: '请检查目录和文件名后重试。',
    },
    WIKI_READ_ONLY: {
      title: '该知识库内容只读',
      detail: '商家记忆由系统自动沉淀，不能在后台直接修改。',
    },
    INVALID_FILE_TYPE: {
      title: '仅支持 Markdown 文档',
      detail: '请使用 .md 后缀的知识库文档。',
    },
    INVALID_WIKI_PARENT: {
      title: '目标目录不存在',
      detail: '请先创建对应业务域，再添加文档。',
    },
    WIKI_NODE_EXISTS: {
      title: '同名文档已存在',
      detail: '请更换文档名称后重试。',
    },
    WIKI_NODE_NOT_FOUND: {
      title: '未找到知识库文档',
      detail: '该文档可能已被删除或路径有误。',
    },
    WIKI_DIRECTORY_NOT_EMPTY: {
      title: '业务域仍包含文档',
      detail: '请确认后使用递归删除。',
    },
    WIKI_VERSION_REQUIRED: {
      title: '缺少文档版本',
      detail: '请重新加载文档后再保存。',
    },
    WIKI_VERSION_CONFLICT: {
      title: '文档已被其他维护者修改',
      detail: '请重新加载最新内容，并保留你当前的修改后再处理。',
    },
    WIKI_DOCUMENT_TOO_LARGE: {
      title: '文档内容过大',
      detail: '请缩短内容后再保存。',
    },
    INVALID_WIKI_ENCODING: {
      title: '文档编码不支持',
      detail: '请使用 UTF-8 编码的文本。',
    },
    INVALID_WIKI_CONTENT: {
      title: '文档内容不合法',
      detail: '请移除不支持的控制字符后重试。',
    },
    WIKI_IO_ERROR: {
      title: '知识库暂时无法写入',
      detail: '请稍后重试；如果持续出现，请联系支持。',
    },

    // —— 前端本地错误码（5 项） ——
    CONFIG: {
      title: '应用配置有误',
      detail: '应用缺少必要的配置项，无法连接后端服务，请联系技术支持。',
    },
    NETWORK: {
      title: '网络连接失败',
      detail: '请检查网络连接后重试。',
    },
    CANCELLED: {
      title: '请求已取消',
      detail: '本次请求已被取消，不会返回结果。',
    },
    STREAM_INTERRUPTED: {
      title: '回答流意外中断',
      detail: '连接在回答完成前中断，请重试。',
    },
    CONTRACT: {
      title: '返回内容不符合预期',
      detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    },
  } satisfies Record<AppErrorCode, { title: string; detail: string }>,
}
