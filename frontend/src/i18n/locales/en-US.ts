import type { MessageSchema } from '../keys'

/**
 * 英文消息目录。必须满足 `zh-CN.ts` 派生出的 `MessageSchema`——多一个 key、
 * 少一个 key 都会在这里编译失败，不需要额外的漂移检查脚本。
 */
export const enUS = {
  appMeta: {
    title: 'Borough Merchant AI Assistant',
  },
  languageSwitcher: {
    switchToChinese: 'Switch to Chinese',
    switchToEnglish: 'Switch to English',
    chinese: 'Chinese',
    english: 'English',
  },
} satisfies MessageSchema
