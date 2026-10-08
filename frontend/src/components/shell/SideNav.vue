<script setup lang="ts">
/**
 * 商家工作台侧栏（W Task 5，设计说明 §2.1、PRD M1）：
 * - 品牌区：Borough 字标 + 商家切换（沿用 `MerchantSwitcher` 的行为）；
 * - 四个分组：工作区（首页 / 商品 / 订单 / 库存）、运营（待审批 / 售后 / 顾客信号 / 记忆）、
 *   运营助手（切换助手栏的按钮，W Task 6 接线）、管理（知识库；进入须管理员令牌，闸门由 `AdminGate` 负责，页面层包裹）；
 * - 左下角账号区打开偏好设置。
 *
 * 侧栏**不放「对话记录」**：对话历史在助手栏头部（Task 6）。
 * 条目上不显示计数徽标：本 Task 没有接数据，不写示意数字（R7）。
 */
import {
  Activity,
  BookOpen,
  Brain,
  House,
  Inbox,
  Package,
  Settings,
  Signal,
  Sparkles,
  Stamp,
  Tag,
  Undo2,
} from '@lucide/vue'
import { computed, onBeforeUnmount, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, type RouteLocationRaw } from 'vue-router'

import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import { useAuthStore } from '@/stores/auth'
import { isApplePlatform } from '@/utils/platform'

import BrandMark from './BrandMark.vue'
import CustomerViewLink from './CustomerViewLink.vue'
import PreferencesPanel from './PreferencesPanel.vue'

type NavKey =
  | 'home'
  | 'catalog'
  | 'orders'
  | 'inventory'
  | 'approvals'
  | 'after-sales'
  | 'signals'
  | 'memory'
  | 'knowledge-base'
  | 'ops-status'

interface NavItem {
  key: NavKey
  labelKey: string
  icon: Component
  to: RouteLocationRaw
  /** 这些路由名下都高亮本条目（例如审批详情页也高亮「待审批」）。 */
  activeFor: readonly string[]
}

interface NavGroup {
  key: 'workspace' | 'operations' | 'admin'
  labelKey: string
  items: readonly NavItem[]
}

const props = withDefaults(defineProps<{ assistantOpen?: boolean }>(), { assistantOpen: false })
const emit = defineEmits<{ 'toggle-assistant': [] }>()

const { t } = useI18n()
const route = useRoute()
const auth = useAuthStore()

const WORKSPACE: NavGroup = {
  key: 'workspace',
  labelKey: 'shell.groups.workspace',
  items: [
    {
      key: 'home',
      labelKey: 'shell.nav.home',
      icon: House,
      to: { name: 'home' },
      activeFor: ['home'],
    },
    {
      key: 'catalog',
      labelKey: 'shell.nav.catalog',
      icon: Tag,
      to: { name: 'catalog' },
      activeFor: ['catalog'],
    },
    {
      key: 'orders',
      labelKey: 'shell.nav.orders',
      icon: Inbox,
      to: { name: 'orders' },
      activeFor: ['orders'],
    },
    {
      key: 'inventory',
      labelKey: 'shell.nav.inventory',
      icon: Package,
      to: { name: 'inventory' },
      activeFor: ['inventory'],
    },
  ],
}

const OPERATIONS: NavGroup = {
  key: 'operations',
  labelKey: 'shell.groups.operations',
  items: [
    {
      key: 'approvals',
      labelKey: 'shell.nav.approvals',
      icon: Stamp,
      to: { name: 'approval-list' },
      activeFor: ['approval-list', 'approval'],
    },
    {
      key: 'after-sales',
      labelKey: 'shell.nav.afterSales',
      icon: Undo2,
      to: { name: 'after-sales' },
      activeFor: ['after-sales'],
    },
    {
      key: 'signals',
      labelKey: 'shell.nav.signals',
      icon: Signal,
      to: { name: 'customer-signals' },
      activeFor: ['customer-signals'],
    },
    {
      key: 'memory',
      labelKey: 'shell.nav.memory',
      icon: Brain,
      to: { name: 'merchant-memory' },
      activeFor: ['merchant-memory'],
    },
  ],
}

// 管理分组：知识库与只读运维看板（N5 B Task 3，D-N5-1），两页都在页面层包 `AdminGate`。
const ADMIN: NavGroup = {
  key: 'admin',
  labelKey: 'shell.groups.admin',
  items: [
    {
      key: 'knowledge-base',
      labelKey: 'shell.nav.knowledgeBase',
      icon: BookOpen,
      to: { name: 'knowledge-base' },
      activeFor: ['knowledge-base'],
    },
    {
      key: 'ops-status',
      labelKey: 'shell.nav.opsStatus',
      icon: Activity,
      to: { name: 'ops-status' },
      activeFor: ['ops-status'],
    },
  ],
}

const currentName = computed(() => (typeof route.name === 'string' ? route.name : ''))

function isActive(item: NavItem): boolean {
  return item.activeFor.includes(currentName.value)
}

const shortcutHint = `${isApplePlatform() ? '⌘' : 'Ctrl'} J`

function selectMerchant(displayName: string): void {
  // 与原 `OpsAssistantView.selectMerchant` 同一守卫：重复点当前商家不能清掉已有会话；
  // `auth.selectByDisplayName` 换商家时会丢弃旧会话并清空全部会话态 Store。
  if (displayName === auth.selected?.displayName) return
  if (!auth.displayNames.includes(displayName)) return
  auth.selectByDisplayName(displayName)
}

// ---------- 账号区 / 偏好设置 ----------
const prefsOpen = ref(false)
const operatorElement = ref<HTMLDivElement | null>(null)
const prefsTrigger = ref<HTMLButtonElement | null>(null)

const avatarText = computed(() => auth.selected?.displayName.trim().charAt(0) || 'B')

function closePrefs(returnFocus = false): void {
  prefsOpen.value = false
  if (returnFocus) prefsTrigger.value?.focus()
}

function onDocumentPointerdown(event: PointerEvent): void {
  if (!(event.target instanceof Node) || operatorElement.value?.contains(event.target)) return
  closePrefs()
}

watch(prefsOpen, (open) => {
  document.removeEventListener('pointerdown', onDocumentPointerdown)
  if (open) document.addEventListener('pointerdown', onDocumentPointerdown)
})

onBeforeUnmount(() => document.removeEventListener('pointerdown', onDocumentPointerdown))
</script>

<template>
  <div class="side-nav">
    <RouterLink class="side-nav__wordmark" :to="{ name: 'home' }" :aria-label="t('shell.homeAria')">
      <BrandMark />
      <span class="side-nav__wordmark-text">
        <b translate="no">Borough</b>
        <span>{{ t('shell.wordmarkSub') }}</span>
      </span>
    </RouterLink>

    <MerchantSwitcher
      v-if="auth.selected"
      variant="side"
      :caption="t('shell.merchantSub')"
      :model-value="auth.selected.displayName"
      :merchants="auth.displayNames"
      @update:model-value="selectMerchant"
    />

    <nav class="side-nav__nav" :aria-label="t('shell.navLabel')">
      <template v-for="(group, index) in [WORKSPACE, OPERATIONS]" :key="group.key">
        <hr v-if="index > 0" />
        <div role="group" :aria-label="t(group.labelKey)" :data-nav-group="group.key">
          <RouterLink
            v-for="item in group.items"
            :key="item.key"
            v-slot="{ href, navigate }"
            :to="item.to"
            custom
          >
            <a
              class="side-nav__link"
              :href="href"
              :data-nav-item="item.key"
              :aria-current="isActive(item) ? 'page' : undefined"
              @click="navigate"
            >
              <component :is="item.icon" :size="18" aria-hidden="true" />
              <span>{{ t(item.labelKey) }}</span>
            </a>
          </RouterLink>
        </div>
      </template>

      <hr />
      <div role="group" :aria-label="t('shell.groups.assistant')" data-nav-group="assistant">
        <button
          type="button"
          class="side-nav__assist"
          :aria-pressed="props.assistantOpen ? 'true' : 'false'"
          :aria-expanded="props.assistantOpen ? 'true' : 'false'"
          aria-controls="assistant-rail"
          @click="emit('toggle-assistant')"
        >
          <Sparkles :size="18" aria-hidden="true" />
          <span>{{ t('shell.nav.assistant') }}</span>
          <span class="side-nav__kbd" aria-hidden="true">{{ shortcutHint }}</span>
        </button>
      </div>

      <hr />
      <div role="group" :aria-label="t(ADMIN.labelKey)" :data-nav-group="ADMIN.key">
        <p class="side-nav__caption" aria-hidden="true">{{ t(ADMIN.labelKey) }}</p>
        <RouterLink
          v-for="item in ADMIN.items"
          :key="item.key"
          v-slot="{ href, navigate }"
          :to="item.to"
          custom
        >
          <a
            class="side-nav__link"
            :href="href"
            :data-nav-item="item.key"
            :aria-current="isActive(item) ? 'page' : undefined"
            @click="navigate"
          >
            <component :is="item.icon" :size="18" aria-hidden="true" />
            <span>{{ t(item.labelKey) }}</span>
          </a>
        </RouterLink>
      </div>
    </nav>

    <div ref="operatorElement" class="side-nav__operator">
      <!-- 「顾客视角」（D-N5-4）：只是新标签链接；未配置顾客端地址或没有会话时不渲染。 -->
      <CustomerViewLink class="side-nav__customer-view" />
      <button
        ref="prefsTrigger"
        type="button"
        class="side-nav__operator-button"
        data-testid="preferences-trigger"
        aria-haspopup="dialog"
        :aria-expanded="prefsOpen ? 'true' : 'false'"
        :aria-label="t('shell.accountAria')"
        @click="prefsOpen = !prefsOpen"
      >
        <span class="side-nav__avatar" aria-hidden="true">{{ avatarText }}</span>
        <span class="side-nav__operator-text">
          <strong>{{ t('shell.account') }}</strong>
          <span>{{ t('shell.accountHint') }}</span>
        </span>
        <Settings :size="18" aria-hidden="true" class="side-nav__gear" />
      </button>
      <!-- 面板放在触发按钮之后：Tab 顺序紧接按钮；视觉上靠绝对定位浮在按钮上方。 -->
      <PreferencesPanel v-if="prefsOpen" class="side-nav__prefs" @close="closePrefs(true)" />
    </div>
  </div>
</template>

<style scoped>
.side-nav {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  min-height: 0;
  padding: 16px 12px 12px;
  color: var(--side-ink);
}

.side-nav__wordmark {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 0 6px;
  color: inherit;
  text-decoration: none;
}

.side-nav__wordmark-text > b {
  display: block;
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1;
  color: #fbf6ea;
}

.side-nav__wordmark-text > span {
  display: block;
  margin-top: 4px;
  font-size: 11.5px;
  letter-spacing: 0.1em;
  color: var(--side-soft);
}

/* 纵向可滚动会裁掉溢出内容；左右各外扩 12px 贴齐侧栏边缘，金色选中条才不会被裁掉。 */
.side-nav__nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
  margin: 0 -12px;
  padding: 0 12px;
  overflow-y: auto;
}

.side-nav__nav > div {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.side-nav__nav hr {
  width: 100%;
  margin: 8px 0;
  border: 0;
  border-top: 1px solid var(--side-line);
}

.side-nav__caption {
  margin: 0 10px 4px;
  font-size: 11.5px;
  letter-spacing: 0.08em;
  color: var(--side-faint);
}

.side-nav__link,
.side-nav__assist {
  position: relative;
  display: flex;
  align-items: center;
  gap: 11px;
  width: 100%;
  padding: 9px 10px;
  border: 0;
  border-radius: 10px;
  color: var(--side-2);
  background: none;
  font-size: 14px;
  text-align: left;
  text-decoration: none;
  transition:
    background-color 150ms,
    color 150ms;
}

.side-nav__link:hover,
.side-nav__assist:hover {
  color: #fff;
  background: var(--side-hover);
}

.side-nav__link[aria-current='page'] {
  color: #fff;
  background: var(--side-active);
  font-weight: 600;
}

/* 金色选中条：贴着侧栏左边缘 */
.side-nav__link[aria-current='page']::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 9px;
  bottom: 9px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--gilt);
}

.side-nav__link :deep(svg),
.side-nav__assist :deep(svg),
.side-nav__gear {
  width: 18px;
  height: 18px;
  flex: none;
}

.side-nav__assist {
  color: var(--side-ink);
  font-weight: 500;
}

.side-nav__assist :deep(svg) {
  color: #e8906c;
}

.side-nav__assist[aria-pressed='true'] {
  color: #fff;
  background: rgba(181, 80, 47, 0.32);
  font-weight: 600;
}

.side-nav__assist[aria-pressed='true'] :deep(svg) {
  color: #ffd2bf;
}

.side-nav__kbd {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--side-faint);
}

.side-nav__operator {
  position: relative;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--side-line);
}

.side-nav__customer-view {
  margin-bottom: 8px;
}

.side-nav__operator-button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border: 0;
  border-radius: 10px;
  color: inherit;
  background: none;
  text-align: left;
  transition: background-color 150ms;
}

.side-nav__operator-button:hover,
.side-nav__operator-button[aria-expanded='true'] {
  background: var(--side-hover);
}

.side-nav__avatar {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--iron);
  background: var(--gilt);
  font-size: 13px;
  font-weight: 700;
}

.side-nav__operator-text {
  min-width: 0;
  flex: 1;
}

.side-nav__operator-text > strong {
  display: block;
  font-size: 13.5px;
  font-weight: 600;
}

.side-nav__operator-text > span {
  display: block;
  overflow: hidden;
  font-size: 12px;
  color: var(--side-soft);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.side-nav__gear {
  color: var(--side-faint);
}

.side-nav__prefs {
  position: absolute;
  left: 0;
  bottom: calc(100% + 6px);
  z-index: 40;
}
</style>
