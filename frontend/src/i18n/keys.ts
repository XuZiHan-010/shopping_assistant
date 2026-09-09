import { zhCN } from './locales/zh-CN'

/**
 * 消息目录的类型形状，由中文目录（事实源）派生。`en-US.ts` 用
 * `satisfies MessageSchema` 校验自己覆盖了完全相同的 key 集合——多一个、
 * 少一个都编译不过，组件里的 `t()` 调用因此天然获得 key 自动补全和编译期
 * 校验，不允许用 `t(key as any)` 绕过。
 */
export type MessageSchema = typeof zhCN
