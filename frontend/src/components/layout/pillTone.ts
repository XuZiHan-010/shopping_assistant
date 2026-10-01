/**
 * 状态胶囊（`StatusPill.vue`）的色调。放在独立 .ts 文件里，供 .ts 模块（如
 * `components/orders/orderStatus.ts`）与组件共用，不从 .vue 的第二个 script 块导出。
 */
export type PillTone = 'ok' | 'warn' | 'danger' | 'info' | 'violet' | 'muted'
