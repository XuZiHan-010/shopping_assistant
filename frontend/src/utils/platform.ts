/**
 * 是否苹果平台：决定快捷键说明显示 ⌘ 还是 Ctrl。
 * 只影响说明文字；真正的按键判定（Task 6）同时接受 metaKey 与 ctrlKey。
 */
export function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  const hint = navigator.platform || navigator.userAgent || ''
  return /Mac|iPhone|iPad|iPod/i.test(hint)
}
