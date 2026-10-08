import { expect, type Page } from '@playwright/test'

/**
 * 横向溢出检查（W Task 11 统一）。
 *
 * 只比较 `document.documentElement.scrollWidth` 在新外壳下恒通过：`body` 设了
 * `overflow-x: clip`，外壳 `.shell` 固定视口高并 `overflow: hidden`，真正滚动的是
 * `main#main`（`overflow: auto`）。所以这里同时要求：
 * - `main#main` 必须存在（不用 `?? 0` 让缺失时空过）；
 * - 页面、`main#main`、以及展开时的助手栏 `#assistant-rail`，内容宽都不超过可视宽。
 *
 * `scrollWidth` 对 `overflow: hidden` 的元素同样返回内容宽，助手栏因此也能查出溢出。
 */
export async function expectNoHorizontalOverflow(page: Page, state: string): Promise<void> {
  const sizes = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>('main#main')
    const rail = document.querySelector<HTMLElement>('#assistant-rail:not([hidden])')
    return {
      pageScroll: document.documentElement.scrollWidth,
      viewport: window.innerWidth,
      main: main ? { scroll: main.scrollWidth, client: main.clientWidth } : null,
      rail: rail ? { scroll: rail.scrollWidth, client: rail.clientWidth } : null,
    }
  })

  expect(sizes.main, `${state}：找不到外壳主视图 main#main`).not.toBeNull()
  expect(
    sizes.pageScroll,
    `${state}：页面宽 ${sizes.pageScroll}px，视口 ${sizes.viewport}px`,
  ).toBeLessThanOrEqual(sizes.viewport)
  if (sizes.main) {
    expect(
      sizes.main.scroll,
      `${state}：主视图内容宽 ${sizes.main.scroll}px，可视宽 ${sizes.main.client}px`,
    ).toBeLessThanOrEqual(sizes.main.client)
  }
  if (sizes.rail) {
    expect(
      sizes.rail.scroll,
      `${state}：助手栏内容宽 ${sizes.rail.scroll}px，可视宽 ${sizes.rail.client}px`,
    ).toBeLessThanOrEqual(sizes.rail.client)
  }
}
