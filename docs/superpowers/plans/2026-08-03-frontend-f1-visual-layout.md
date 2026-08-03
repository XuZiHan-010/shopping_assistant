# Frontend F1 Visual Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Borough 前端 F1 的正式品牌、响应式三栏主布局、商家切换器及可验证的视觉基础。

**Architecture:** 全局样式由 `styles.css` 聚合 tokens 与 base；`AssistantView` 只组合页面区域。`ConversationColumn` 组合独立的 `ChatComposer`，商家切换器保持一个实例并由 CSS Grid 在既有 560px 断点改变位置。F1 的最小 Chat Store 只提供空会话及 `reset()`，不涉及 API 或领域模型。

**Tech Stack:** Vue 3、TypeScript、Pinia、Lucide Vue、Vitest、Vue Test Utils、Playwright、CSS Media Queries。

## Global Constraints

- 所有用户可见文案使用中文，代码标识符使用英文。
- `yshopping-prototype/` 与 `yshopping-merchant-ai 4/` 只读；不得复制旧 logo 或留下旧品牌标识。
- 不读取或修改 `docs/api.json`、`src/api/generated.ts`；组件不直接消费生成类型，也不转换 API 字段。
- F1 不接 API、SSE、真实 LLM、附件、Token、`merchant_id` 或登录体系。
- 不增加 1240px、860px、560px 之外的新响应式断点；561–580px 用可收缩布局解决。
- 项目规则禁止未经明确授权的 Git commit/push/tag/PR；本计划的每项以测试通过替代 commit。

---

### Task 1: 建立 Borough 全局视觉基础

**Files:**
- Create: `frontend/src/assets/tokens.css`
- Create: `frontend/src/assets/base.css`
- Create: `frontend/src/assets/styles.css`
- Create: `frontend/public/borough-logo.svg`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/index.html`

**Produces:** `main.ts` 通过 `import '@/assets/styles.css'` 加载唯一全局入口；所有页面可使用 `--color-*`、`--space-*`、`--radius-*`、`--shadow-*` 变量。

- [ ] **Step 1: 写入基础样式和品牌资产。**

  `tokens.css` 定义以下语义变量，不使用旧品牌前缀：

  ```css
  :root {
    --color-primary: #4f6ef7;
    --color-primary-strong: #3f5bd8;
    --color-surface: rgba(255, 255, 255, 0.94);
    --color-border: #e1e7f0;
    --color-text: #182033;
    --radius-card: 13px;
    --shadow-card: 0 12px 34px rgba(37, 52, 82, 0.08);
  }
  ```

  `base.css` 包含 `box-sizing`、`min-width: 320px`、背景渐变、`:focus-visible`、`prefers-reduced-motion` 与 `overflow-x: clip` 的页面保护。`borough-logo.svg` 使用 Borough 购物篮抽象图形及独立文字描述。`index.html` 的 title 与 description 使用 Borough。

- [ ] **Step 2: 从 `main.ts` 导入样式聚合入口。**

  ```ts
  import '@/assets/styles.css'
  ```

- [ ] **Step 3: 运行类型与构建验证。**

  Run: `npm run typecheck; npm run build`（工作目录 `frontend/`）

  Expected: 两条命令退出码为 0。

### Task 2: 实现最小 Chat 状态和商家切换器

**Files:**
- Create: `frontend/src/stores/chat.ts`
- Create: `frontend/src/components/layout/MerchantSwitcher.vue`
- Create: `frontend/src/components/layout/MerchantSwitcher.spec.ts`

**Interfaces:**
- Produces: `useChatStore(): { isEmptyConversation: boolean; reset(): void }`。
- Produces: `MerchantSwitcher` props `modelValue: string`、`merchants: readonly string[]`，事件 `update:modelValue`。
- Consumes: Pinia 与 Lucide 的 `ChevronDown`。

- [ ] **Step 1: 写失败的 MerchantSwitcher 组件测试。**

  ```ts
  it('选择商家时更新 v-model，且名称始终可见', async () => {
    const wrapper = mount(MerchantSwitcher, {
      props: { modelValue: 'Borough商家100', merchants: ['Borough商家100', 'Borough商家101'] },
    })
    await wrapper.get('button').trigger('click')
    await wrapper.get('[role="option"][data-merchant="Borough商家101"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['Borough商家101'])
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/components/layout/MerchantSwitcher.spec.ts`（工作目录 `frontend/`）

  Expected: FAIL，因为组件尚不存在。

- [ ] **Step 3: 实现最小 Store 与可访问的切换器。**

  ```ts
  export const useChatStore = defineStore('chat', () => {
    const isEmptyConversation = ref(true)
    const reset = () => { isEmptyConversation.value = true }
    return { isEmptyConversation, reset }
  })
  ```

  切换器以按钮触发受控菜单，具有 `aria-expanded`、可见状态点与显示名；不接 Token。组件只发出选择事件，重置由页面组合层执行。

- [ ] **Step 4: 运行组件测试。**

  Run: `npm run test -- src/components/layout/MerchantSwitcher.spec.ts`

  Expected: PASS。

### Task 3: 拆分中列与输入区视觉外壳

**Files:**
- Create: `frontend/src/components/chat/ChatComposer.vue`
- Create: `frontend/src/components/chat/ChatComposer.spec.ts`
- Create: `frontend/src/components/chat/ConversationColumn.vue`
- Create: `frontend/src/components/chat/ConversationColumn.spec.ts`

**Interfaces:**
- Produces: `ChatComposer` 事件 `submit`，payload 为当前文本；F1 不由该事件发起网络请求。
- Produces: `ConversationColumn` 作为包含消息滚动区与 `<ChatComposer />` 的中列布局。
- Consumes: Lucide 的 `Paperclip`、`ArrowUp`、`Sparkles`。

- [ ] **Step 1: 写失败的组件边界测试。**

  ```ts
  it('ConversationColumn 组合独立的 ChatComposer', () => {
    const wrapper = mount(ConversationColumn)
    expect(wrapper.findComponent(ChatComposer).exists()).toBe(true)
    expect(wrapper.get('[data-testid="chat-list"]').exists()).toBe(true)
  })

  it('ChatComposer 提交文本但不直接调用网络层', async () => {
    const wrapper = mount(ChatComposer)
    await wrapper.get('textarea').setValue('查看昨天 GMV')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toEqual([['查看昨天 GMV']])
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/components/chat/ChatComposer.spec.ts src/components/chat/ConversationColumn.spec.ts`

  Expected: FAIL，因为两个组件尚不存在。

- [ ] **Step 3: 实现组件。**

  Composer 使用原型风格的 `form`、`textarea`、附件按钮和发送按钮，提交时仅 emit；ConversationColumn 渲染欢迎卡、空状态、可滚动消息区及 Composer。F1 不导入 Adapter、生成类型、API Client 或附件逻辑。

- [ ] **Step 4: 运行组件测试。**

  Run: `npm run test -- src/components/chat/ChatComposer.spec.ts src/components/chat/ConversationColumn.spec.ts`

  Expected: PASS。

### Task 4: 组合响应式 AssistantView

**Files:**
- Modify: `frontend/src/views/AssistantView.vue`
- Create: `frontend/src/views/AssistantView.spec.ts`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Consumes: `ConversationColumn`、`MerchantSwitcher`、`useChatStore`、Vue Router 的 `RouterLink`。
- Produces: 页面 landmark：header、left/right complementary sidebars、main conversation region；`data-testid` 为 E2E 提供稳定测点。

- [ ] **Step 1: 写失败的页面组合测试。**

  ```ts
  it('渲染顶栏、三栏区域和独立输入区', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(AssistantView, {
      global: { plugins: [pinia], stubs: { RouterLink: true } },
    })
    expect(wrapper.get('[data-testid="workspace-grid"]').exists()).toBe(true)
    expect(wrapper.findAll('aside')).toHaveLength(2)
    expect(wrapper.findComponent(ConversationColumn).exists()).toBe(true)
    expect(wrapper.findComponent(MerchantSwitcher).exists()).toBe(true)
  })
  ```

- [ ] **Step 2: 运行测试确认失败。**

  Run: `npm run test -- src/views/AssistantView.spec.ts`

  Expected: FAIL，因为 F0 页面没有三栏组件。

- [ ] **Step 3: 实现组合与响应式 CSS。**

  使用一个 MerchantSwitcher 实例和 CSS Grid placement。商家列表硬编码为演示显示名，并以注释说明 F2 由 Auth Store 替换；选中商家与新会话均调用 `chatStore.reset()`。顶部按钮使用中文可访问名称，知识库跳转 `/knowledge-base`。为 561–580px 设置可收缩品牌标题及不可换行操作区，不添加媒体查询断点。将 `App.vue` 的全局错误条改用 tokens，保留 `role="status"`。

- [ ] **Step 4: 运行页面测试。**

  Run: `npm run test -- src/views/AssistantView.spec.ts`

  Expected: PASS。

### Task 5: 重整 E2E 并完成验收文档

**Files:**
- Create: `frontend/e2e/assistant.spec.ts`
- Create: `frontend/e2e/responsive.spec.ts`
- Delete: `frontend/e2e/skeleton.spec.ts`
- Modify: `docs/frontend-development-plan.md`
- Modify: `docs/project-progress.md`

**Interfaces:**
- `assistant.spec.ts` 吸收 F0 的路由、知识库、未知路径与控制台错误覆盖。
- `responsive.spec.ts` 使用 `data-testid` 与计算样式验证布局；不使用 `toHaveScreenshot`。

- [ ] **Step 1: 编写 E2E 断言。**

  ```ts
  test('1440px 保持三栏宽度约束', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto('/')
    const widths = await page.locator('[data-testid="workspace-grid"]').evaluate((grid) => {
      const [left, chat, right] = [...grid.children].map((node) => node.getBoundingClientRect().width)
      return { left, chat, right }
    })
    expect(widths.left).toBeGreaterThanOrEqual(230)
    expect(widths.left).toBeLessThanOrEqual(280)
    expect(widths.chat).toBeLessThanOrEqual(760)
    expect(widths.right).toBeGreaterThanOrEqual(230)
  })
  ```

  另建测试：561px 和 580px 头部 `scrollWidth <= clientWidth`；390×844 的 textarea 可见且可聚焦；360px 页面根元素无横向溢出；`page.emulateMedia({ reducedMotion: 'reduce' })` 后新会话按钮的 transition 时长小于基础值。

- [ ] **Step 2: 将 F0 覆盖迁入正式测试文件，再删除 skeleton。**

  `assistant.spec.ts` 保留三个已有场景的语义：助手入口与无控制台错误、知识库占位页、`/login` 重定向到 `/`。

- [ ] **Step 3: 运行全量门禁。**

  Run: `npm run lint; npm run format:check; npm run codegen:check; npm run typecheck; npm run test; npm run test:e2e; npm run build`（工作目录 `frontend/`）

  Expected: 全部退出码为 0。

- [ ] **Step 4: 人工视觉核对与文档同步。**

  在 1440×1000 运行本地前端，与只读 Prototype 的主布局进行一次人工比对；不保存自行生成的截图快照。将结论与自动化结果写入 `docs/project-progress.md`。同时在 `docs/frontend-development-plan.md` §4 的 `components/` 树中补入 `layout/`。
