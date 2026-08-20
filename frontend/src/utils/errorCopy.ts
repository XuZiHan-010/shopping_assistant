/**
 * `AppErrorCode` → 中文展示文案的穷尽映射表（前端方案 §10）。
 *
 * 用 `Record<AppErrorCode, ErrorCopy>` 而非 `Partial<...>` + default 分支：
 * 后端在 `generated.ts` 里新增错误码时，`AppErrorCode` 联合类型跟着变大，这张表
 * 会因为缺一项而在 typecheck 阶段直接报错——新码不会静默落进某个笼统的默认文案。
 * 这是本任务真正的防线；`errorCopy.spec.ts` 里的穷尽性测试只是防止有人图省事把
 * 这里改回 `Partial`。
 */
import type { AppError, AppErrorCode } from '@/api/errors'

export interface ErrorCopy {
  /** 简短标题，用于弹层/横幅的第一行。 */
  title: string
  /** 补充说明，告诉用户发生了什么、能做什么。 */
  detail: string
  /** 展示位置：内联提示 / 全局遮罩或横幅 / 不提示用户、只静默上报。 */
  surface: 'message' | 'global' | 'silent-report'
  /** 建议的下一步操作，供调用方决定要不要渲染操作按钮。 */
  action: 'retry' | 'reselect-merchant' | 'reask' | 'none'
}

const COPY: Record<AppErrorCode, ErrorCopy> = {
  // —— 后端 ErrorCode（14 项） ——
  AUTH_REQUIRED: {
    title: '登录状态已失效',
    detail: '请重新选择商家登录后再试。',
    surface: 'global',
    action: 'reselect-merchant',
  },
  MERCHANT_SCOPE_VIOLATION: {
    title: '无权访问该商家的数据',
    detail: '当前登录身份没有权限查看这份数据，请确认选择的商家是否正确。',
    surface: 'global',
    action: 'reselect-merchant',
  },
  NOT_FOUND: {
    title: '未找到对应内容',
    detail: '你要查看的内容可能已被删除，或者链接有误。',
    surface: 'message',
    action: 'none',
  },
  METHOD_NOT_ALLOWED: {
    title: '请求方式不受支持',
    detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    surface: 'silent-report',
    action: 'none',
  },
  INVALID_REQUEST: {
    title: '请求内容有误',
    detail: '请检查输入内容后重新提交。',
    surface: 'message',
    action: 'reask',
  },
  IDEMPOTENCY_KEY_REUSED: {
    title: '请求被判定为重复提交',
    detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    surface: 'silent-report',
    action: 'none',
  },
  REQUEST_IN_PROGRESS: {
    title: '上一条请求仍在处理',
    detail: '请等待当前回答完成后，再发送新的问题。',
    surface: 'message',
    action: 'none',
  },
  DATA_SOURCE_UNAVAILABLE: {
    title: '经营数据暂时无法访问',
    detail: '数据查询服务暂不可用，请稍后重试。',
    surface: 'message',
    action: 'retry',
  },
  EXPORT_LINK_EXPIRED: {
    title: '导出链接已过期',
    detail: '请重新提问，系统会为你生成新的导出链接。',
    surface: 'message',
    action: 'reask',
  },
  RATE_LIMITED: {
    title: '请求过于频繁',
    detail: '请稍等片刻后再试。',
    surface: 'message',
    action: 'retry',
  },
  LLM_BUDGET_EXCEEDED: {
    title: '今日智能问答额度已用完',
    detail: '为控制成本，AI 问答的当日额度已达上限，请明天再来，或联系客服提升额度。',
    surface: 'global',
    action: 'none',
  },
  FORBIDDEN: {
    title: '没有权限执行该操作',
    detail: '当前账号没有权限执行这个操作，如需继续请联系管理员。',
    surface: 'message',
    action: 'none',
  },
  HTTP_ERROR: {
    title: '请求失败',
    detail: '服务暂时出现问题，请稍后重试；如果持续出现，请联系支持。',
    surface: 'message',
    action: 'retry',
  },
  INTERNAL_ERROR: {
    title: '服务器出现内部错误',
    detail: '我们已记录这个问题，请稍后重试；如果持续出现，请联系支持。',
    surface: 'message',
    action: 'retry',
  },
  INVALID_WIKI_PATH: {
    title: '知识库路径不合法',
    detail: '请检查目录和文件名后重试。',
    surface: 'message',
    action: 'none',
  },
  WIKI_READ_ONLY: {
    title: '该知识库内容只读',
    detail: '商家记忆由系统自动沉淀，不能在后台直接修改。',
    surface: 'message',
    action: 'none',
  },
  INVALID_FILE_TYPE: {
    title: '仅支持 Markdown 文档',
    detail: '请使用 .md 后缀的知识库文档。',
    surface: 'message',
    action: 'none',
  },
  INVALID_WIKI_PARENT: {
    title: '目标目录不存在',
    detail: '请先创建对应业务域，再添加文档。',
    surface: 'message',
    action: 'none',
  },
  WIKI_NODE_EXISTS: {
    title: '同名文档已存在',
    detail: '请更换文档名称后重试。',
    surface: 'message',
    action: 'none',
  },
  WIKI_NODE_NOT_FOUND: {
    title: '未找到知识库文档',
    detail: '该文档可能已被删除或路径有误。',
    surface: 'message',
    action: 'none',
  },
  WIKI_DIRECTORY_NOT_EMPTY: {
    title: '业务域仍包含文档',
    detail: '请确认后使用递归删除。',
    surface: 'message',
    action: 'none',
  },
  WIKI_VERSION_REQUIRED: {
    title: '缺少文档版本',
    detail: '请重新加载文档后再保存。',
    surface: 'message',
    action: 'none',
  },
  WIKI_VERSION_CONFLICT: {
    title: '文档已被其他维护者修改',
    detail: '请重新加载最新内容，并保留你当前的修改后再处理。',
    surface: 'message',
    action: 'none',
  },
  WIKI_DOCUMENT_TOO_LARGE: {
    title: '文档内容过大',
    detail: '请缩短内容后再保存。',
    surface: 'message',
    action: 'none',
  },
  INVALID_WIKI_ENCODING: {
    title: '文档编码不支持',
    detail: '请使用 UTF-8 编码的文本。',
    surface: 'message',
    action: 'none',
  },
  INVALID_WIKI_CONTENT: {
    title: '文档内容不合法',
    detail: '请移除不支持的控制字符后重试。',
    surface: 'message',
    action: 'none',
  },
  WIKI_IO_ERROR: {
    title: '知识库暂时无法写入',
    detail: '请稍后重试；如果持续出现，请联系支持。',
    surface: 'message',
    action: 'retry',
  },

  // —— 前端本地错误码（5 项） ——
  CONFIG: {
    title: '应用配置有误',
    detail: '应用缺少必要的配置项，无法连接后端服务，请联系技术支持。',
    surface: 'global',
    action: 'none',
  },
  NETWORK: {
    title: '网络连接失败',
    detail: '请检查网络连接后重试。',
    surface: 'message',
    action: 'retry',
  },
  CANCELLED: {
    title: '请求已取消',
    detail: '本次请求已被取消，不会返回结果。',
    surface: 'message',
    action: 'none',
  },
  STREAM_INTERRUPTED: {
    title: '回答流意外中断',
    detail: '连接在回答完成前中断，请重试。',
    surface: 'message',
    action: 'retry',
  },
  CONTRACT: {
    title: '返回内容不符合预期',
    detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    surface: 'silent-report',
    action: 'none',
  },
}

/** 把归一化后的 `AppError` 翻译成可直接展示给用户的中文文案。 */
export function describeError(error: AppError): ErrorCopy {
  return COPY[error.code]
}
