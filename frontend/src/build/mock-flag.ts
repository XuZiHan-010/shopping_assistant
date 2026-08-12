/**
 * 生产构建禁止启用 Mock 传输。
 *
 * 为什么不靠 `mock:check`：那个脚本扫的是 dist 里有没有 fixture 载荷，而
 * `VITE_USE_MOCK=true` 只是让 `src/api/transport.ts::isMockEnabled()` 返回 true，
 * mock 传输层代码本身未必包含可被识别的 fixture 字符串——事后扫描会漏。
 * 这里在配置解析阶段就让构建非零退出。
 *
 * 本模块只被 vite.config.ts 导入，不进应用产物。
 */
export function assertMockDisabledInProduction(
  mode: string,
  env: Record<string, string | undefined>,
): void {
  if (mode !== 'production') return
  // 判定标准必须与 src/api/transport.ts::isMockEnabled() 完全一致。
  if (env.VITE_USE_MOCK === 'true') {
    throw new Error(
      '生产构建禁止启用 Mock：检测到 VITE_USE_MOCK=true。' +
        '生产环境必须连真实后端，请移除该变量或设为 false。',
    )
  }
}
