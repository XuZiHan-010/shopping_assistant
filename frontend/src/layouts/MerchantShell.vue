<script setup lang="ts">
/**
 * 商家工作台外壳（W Task 5，设计说明 §2.1、§3.2）：布局路由，三列——
 * 铸铁绿侧栏、主视图（子路由）、助手栏插槽。
 *
 * - 助手栏 `AssistantRail`（W Task 6）常驻 `#assistant-rail`，默认收起，开合状态在
 *   `stores/rail.ts`。打开方式：侧栏与顶栏的「运营助手」按钮、页面上任意「问助手」、
 *   `Ctrl/⌘ + J`（`preventDefault`，Chrome 默认会打开下载页；输入框聚焦时同样生效）、
 *   `?assistant=open`（`/ops-assistant` 旧地址的落点，裁定 A：读到后打开，带 `conversation`
 *   时打开那段对话，再只从地址里去掉 `assistant`）。Esc 收起：1100px 以下（抽屉带遮罩）
 *   随时可收；宽屏只在焦点位于助手栏里时收，免得抢走页面自身弹层的 Esc。收起时焦点
 *   若在助手栏里，交还给打开它的控件。
 * - 界面字号用 `zoom: var(--scale)` 整体缩放（`<html data-size>`，见 tokens.css）。
 * - 820px 以下侧栏改抽屉，出现顶栏。打开抽屉时焦点移进抽屉；Escape 或点遮罩关闭，
 *   焦点回到菜单按钮（抽屉内的弹层先处理 Escape 并 `preventDefault()`，此时抽屉不关）。
 * - 切换商家后按商家重新挂载子页面：旧会话的数据随会话态 Store 一起清空，
 *   子页面在挂载时用新会话重新取数，不会停在空白或残留上一家的数据。
 */
import { Menu, Sparkles } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AssistantRail from '@/components/shell/AssistantRail.vue'
import BrandMark from '@/components/shell/BrandMark.vue'
import SideNav from '@/components/shell/SideNav.vue'
import { useAuthStore } from '@/stores/auth'
import { isRailShortcut, useRailStore } from '@/stores/rail'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const rail = useRailStore()

const railOpen = computed(() => rail.open)
const sideOpen = ref(false)

// 只在「从一个商家换到另一个商家」时递增；首次恢复出当前商家（undefined → 某商家）
// 不算切换，否则刚挂载、正在取数的子页面会被无谓地重建一次，重复发请求。
const merchantEpoch = ref(0)
watch(
  () => auth.selected?.merchantId,
  (next, previous) => {
    if (previous && next && next !== previous) merchantEpoch.value += 1
  },
)

const sideElement = ref<HTMLElement | null>(null)
const menuButton = ref<HTMLButtonElement | null>(null)
const railElement = ref<HTMLElement | null>(null)
const topAssistButton = ref<HTMLButtonElement | null>(null)

/** 窄屏侧栏抽屉里点「运营助手」时先收起抽屉，助手栏抽屉才不会被盖住。 */
function toggleAssistant(): void {
  if (sideOpen.value) sideOpen.value = false
  rail.toggle()
}

// ---------- 助手栏：焦点交接 ----------
let railReturnTarget: HTMLElement | null = null

function focusAfterRailClosed(): void {
  const target = railReturnTarget
  railReturnTarget = null
  if (target && target !== document.body && target.isConnected) {
    target.focus()
    if (document.activeElement === target) return
  }
  // 打开它的控件不可见（例如已收起的侧栏抽屉）时，退到侧栏或顶栏的「运营助手」按钮。
  const sideAssist = sideElement.value?.querySelector<HTMLElement>(
    '[aria-controls="assistant-rail"]',
  )
  sideAssist?.focus()
  if (document.activeElement !== sideAssist) topAssistButton.value?.focus()
}

// 默认 `pre`：DOM 更新（给助手栏加上 `hidden`）之前读取焦点位置。
watch(
  () => rail.open,
  (open) => {
    const active = document.activeElement as HTMLElement | null
    if (open) {
      railReturnTarget = active && !railElement.value?.contains(active) ? active : null
      return
    }
    if (active && railElement.value?.contains(active)) void nextTick(focusAfterRailClosed)
    else railReturnTarget = null
  },
)

// ---------- `?assistant=open`（裁定 A） ----------
watch(
  () => route.query.assistant,
  (value) => {
    if (value !== 'open') return
    const conversation = route.query.conversation
    if (typeof conversation === 'string' && conversation) rail.openConversation(conversation)
    else rail.show()
    const rest = { ...route.query }
    delete rest.assistant
    void router.replace({ query: rest, hash: route.hash })
  },
  { immediate: true },
)

function isNarrow(): boolean {
  return typeof window.matchMedia === 'function'
    ? window.matchMedia('(max-width: 1100px)').matches
    : false
}

/**
 * 捕获阶段处理快捷键：页面里的控件即便阻止冒泡，`Ctrl/⌘ + J` 也照样生效。
 * 页面上有打开的模态对话框（任何 `aria-modal="true"` 元素，例如订单详情抽屉）时只拦下
 * 浏览器默认行为、不切换助手栏——否则助手栏会开在遮罩后面，焦点也会跑出模态框。
 */
function onWindowKeydownCapture(event: KeyboardEvent): void {
  if (!isRailShortcut(event)) return
  event.preventDefault()
  if (document.querySelector('[aria-modal="true"]')) return
  toggleAssistant()
}

async function openSide(): Promise<void> {
  sideOpen.value = true
  await nextTick()
  const first = sideElement.value?.querySelector<HTMLElement>('a[href], button, select')
  ;(first ?? sideElement.value)?.focus()
}

function closeSide(returnFocus: boolean): void {
  sideOpen.value = false
  if (returnFocus) menuButton.value?.focus()
}

/**
 * 挂在 window 上（冒泡最末端）：抽屉内的偏好面板、商家菜单都在 document 上监听 Escape
 * 并 `preventDefault()`，它们先处理，这里看到 `defaultPrevented` 就不再关抽屉。
 */
function onWindowKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  if (sideOpen.value) {
    event.preventDefault()
    closeSide(true)
    return
  }
  if (!rail.open) return
  const active = document.activeElement
  if (isNarrow() || (active && railElement.value?.contains(active))) {
    event.preventDefault()
    rail.hide()
  }
}

// 点侧栏链接换页后自动收起抽屉；焦点交给新页面，不拉回菜单按钮。
watch(
  () => route.fullPath,
  () => closeSide(false),
)

onMounted(() => {
  // 直接打开任意子页面（或刷新）时，商家切换器需要先有演示商家列表与当前商家；
  // 子页面自己的 `ensureSession()` 也会兜底，这里先做让切换器更快出现。
  if (!auth.selected) void auth.restore()
  window.addEventListener('keydown', onWindowKeydownCapture, true)
  window.addEventListener('keydown', onWindowKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydownCapture, true)
  window.removeEventListener('keydown', onWindowKeydown)
})
</script>

<template>
  <div
    class="shell"
    data-testid="merchant-shell"
    :data-rail="railOpen ? 'open' : 'closed'"
    :data-side="sideOpen ? 'open' : 'closed'"
  >
    <a class="skip-link" href="#main">{{ t('shell.skip') }}</a>

    <button
      v-if="sideOpen"
      class="shell__backdrop"
      type="button"
      :aria-label="t('shell.closeNav')"
      @click="closeSide(true)"
    ></button>

    <aside
      id="side-nav"
      ref="sideElement"
      class="shell__side"
      tabindex="-1"
      :aria-label="t('shell.sideLabel')"
    >
      <SideNav :assistant-open="railOpen" @toggle-assistant="toggleAssistant" />
    </aside>

    <main id="main" class="shell__main" tabindex="-1">
      <div class="shell__topbar">
        <button
          ref="menuButton"
          class="shell__icon-button"
          type="button"
          aria-controls="side-nav"
          :aria-expanded="sideOpen ? 'true' : 'false'"
          :aria-label="t('shell.openNav')"
          @click="openSide"
        >
          <Menu :size="18" aria-hidden="true" />
        </button>
        <BrandMark class="shell__topbar-mark" />
        <strong translate="no">{{ auth.selected?.displayName ?? 'Borough' }}</strong>
        <button
          ref="topAssistButton"
          class="shell__assist-top"
          type="button"
          aria-controls="assistant-rail"
          :aria-pressed="railOpen ? 'true' : 'false'"
          :aria-expanded="railOpen ? 'true' : 'false'"
          @click="toggleAssistant"
        >
          <Sparkles :size="14" aria-hidden="true" />
          <span>{{ t('shell.nav.assistant') }}</span>
        </button>
      </div>

      <RouterView v-slot="{ Component }">
        <component :is="Component" :key="merchantEpoch" />
      </RouterView>
    </main>

    <!-- 1100px 以下助手栏是抽屉：遮罩只在那时显示（见样式），点击收起。 -->
    <button
      v-if="railOpen"
      class="shell__rail-backdrop"
      type="button"
      data-testid="rail-backdrop"
      :aria-label="t('shell.railClose')"
      @click="rail.hide()"
    ></button>

    <aside
      id="assistant-rail"
      ref="railElement"
      class="shell__rail"
      :aria-label="t('shell.railLabel')"
      :data-state="railOpen ? 'open' : 'closed'"
      :hidden="!railOpen"
    >
      <!-- 收起时只隐藏、不卸载：输入框里的草稿、当前对话与历史面板都保留。 -->
      <AssistantRail />
    </aside>
  </div>
</template>

<style scoped>
.shell {
  zoom: var(--scale);
  display: grid;
  grid-template-columns: var(--side-w) minmax(0, 1fr) 0;
  height: calc(100svh / var(--scale));
  overflow: hidden;
  transition: grid-template-columns 260ms var(--ease);
}

.shell[data-rail='open'] {
  grid-template-columns: var(--side-w) minmax(0, 1fr) var(--rail-w);
}

.skip-link {
  position: fixed;
  left: 12px;
  top: -60px;
  z-index: 100;
  padding: 10px 14px;
  border-radius: 10px;
  color: var(--ground);
  background: var(--ink);
  text-decoration: none;
  transition: top 160ms var(--ease);
}

.skip-link:focus {
  top: 12px;
}

.shell__side {
  position: relative;
  min-height: 0;
  background: var(--side-bg);
  border-right: 1px solid rgba(0, 0, 0, 0.2);
}

.shell__side:focus {
  outline: none;
}

.shell__main {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

.shell__main:focus {
  outline: none;
}

.shell__topbar {
  display: none;
}

.shell__rail {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--chrome);
  border-left: 1px solid var(--line);
}

.shell__backdrop,
.shell__rail-backdrop {
  display: none;
}

@media (max-width: 1100px) {
  .shell,
  .shell[data-rail='open'] {
    grid-template-columns: var(--side-w) minmax(0, 1fr);
  }

  .shell__rail {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 60;
    width: min(var(--rail-w), 100%);
    box-shadow: var(--shadow-lg);
  }

  .shell__rail-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    border: 0;
    background: rgba(10, 16, 13, 0.4);
  }
}

@media (max-width: 820px) {
  .shell,
  .shell[data-rail='open'] {
    grid-template-columns: minmax(0, 1fr);
  }

  .shell__side {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 70;
    width: min(280px, 86%);
    transform: translateX(-100%);
    visibility: hidden;
    transition:
      transform 240ms var(--ease),
      visibility 0s linear 240ms;
  }

  .shell[data-side='open'] .shell__side {
    transform: none;
    visibility: visible;
    box-shadow: var(--shadow-lg);
    transition: transform 240ms var(--ease);
  }

  .shell[data-side='open'] .shell__backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 65;
    border: 0;
    background: rgba(10, 16, 13, 0.4);
  }

  .shell__topbar {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 12px;
    background: var(--chrome);
    border-bottom: 1px solid var(--line);
  }

  .shell__topbar > strong {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: 14.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .shell__topbar-mark {
    width: 30px;
    height: 30px;
  }
}

.shell__icon-button {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--ink-soft);
  background: none;
  transition:
    background-color 150ms,
    color 150ms;
}

.shell__icon-button:hover {
  color: var(--ink);
  background: var(--hover);
}

.shell__icon-button :deep(svg) {
  width: 18px;
  height: 18px;
}

.shell__assist-top {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 11px;
  border: 1px solid var(--line-strong);
  border-radius: 99px;
  color: var(--ink);
  background: var(--card);
  font-size: 13px;
  font-weight: 600;
}

.shell__assist-top :deep(svg) {
  width: 14px;
  height: 14px;
  color: var(--accent);
}
</style>
