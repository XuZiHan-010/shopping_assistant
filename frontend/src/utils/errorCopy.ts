/**
 * `AppErrorCode` → 展示文案的穷尽映射（前端方案 §10）。
 *
 * 文案本身（`title`/`detail`）住在消息目录 `i18n/locales/{zh-CN,en-US}.ts`
 * 的 `errorCopy` 子树里，跟随 `useLocaleStore()` 当前语言渲染；这里只按
 * `error.code` 拼出对应的目录 key 交给 `i18n.global.t()`。`zh-CN.ts` 用
 * `satisfies Record<AppErrorCode, ...>` 保证文案穷尽——后端新增错误码时会在
 * typecheck 阶段直接报错，不会静默漏掉展示文案。
 *
 * `surface`/`action` 是纯行为分支用的协议枚举，不是给用户看的文案，因此
 * **不进消息目录**，仍以 `Record<AppErrorCode, ...>` 留在这里；同样的
 * 穷尽性保证方式，新错误码缺一项会在 typecheck 阶段报错。
 */
import type { AppError, AppErrorCode } from '@/api/errors'
import { i18n } from '@/i18n'

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

type Behavior = Pick<ErrorCopy, 'surface' | 'action'>

const BEHAVIOR: Record<AppErrorCode, Behavior> = {
  // —— 后端 ErrorCode（28 项） ——
  AUTH_REQUIRED: { surface: 'global', action: 'reselect-merchant' },
  MERCHANT_SCOPE_VIOLATION: { surface: 'global', action: 'reselect-merchant' },
  NOT_FOUND: { surface: 'message', action: 'none' },
  METHOD_NOT_ALLOWED: { surface: 'silent-report', action: 'none' },
  INVALID_REQUEST: { surface: 'message', action: 'reask' },
  IDEMPOTENCY_KEY_REUSED: { surface: 'silent-report', action: 'none' },
  REQUEST_IN_PROGRESS: { surface: 'message', action: 'none' },
  DAILY_REPORT_FEEDBACK_CONFLICT: { surface: 'silent-report', action: 'none' },
  DATA_SOURCE_UNAVAILABLE: { surface: 'message', action: 'retry' },
  EXPORT_LINK_EXPIRED: { surface: 'message', action: 'reask' },
  RATE_LIMITED: { surface: 'message', action: 'retry' },
  LLM_BUDGET_EXCEEDED: { surface: 'global', action: 'none' },
  FORBIDDEN: { surface: 'message', action: 'none' },
  HTTP_ERROR: { surface: 'message', action: 'retry' },
  INTERNAL_ERROR: { surface: 'message', action: 'retry' },
  INVALID_WIKI_PATH: { surface: 'message', action: 'none' },
  WIKI_READ_ONLY: { surface: 'message', action: 'none' },
  INVALID_FILE_TYPE: { surface: 'message', action: 'none' },
  INVALID_WIKI_PARENT: { surface: 'message', action: 'none' },
  WIKI_NODE_EXISTS: { surface: 'message', action: 'none' },
  WIKI_NODE_NOT_FOUND: { surface: 'message', action: 'none' },
  WIKI_DIRECTORY_NOT_EMPTY: { surface: 'message', action: 'none' },
  WIKI_VERSION_REQUIRED: { surface: 'message', action: 'none' },
  WIKI_VERSION_CONFLICT: { surface: 'message', action: 'none' },
  WIKI_DOCUMENT_TOO_LARGE: { surface: 'message', action: 'none' },
  INVALID_WIKI_ENCODING: { surface: 'message', action: 'none' },
  INVALID_WIKI_CONTENT: { surface: 'message', action: 'none' },
  WIKI_IO_ERROR: { surface: 'message', action: 'retry' },

  // —— 前端本地错误码（5 项） ——
  CONFIG: { surface: 'global', action: 'none' },
  NETWORK: { surface: 'message', action: 'retry' },
  CANCELLED: { surface: 'message', action: 'none' },
  STREAM_INTERRUPTED: { surface: 'message', action: 'retry' },
  CONTRACT: { surface: 'silent-report', action: 'none' },
}

/** 把归一化后的 `AppError` 翻译成可直接展示给用户的当前语言文案。 */
export function describeError(error: AppError): ErrorCopy {
  const code = error.code

  return {
    title: i18n.global.t(`errorCopy.${code}.title`),
    detail: i18n.global.t(`errorCopy.${code}.detail`),
    ...BEHAVIOR[code],
  }
}
