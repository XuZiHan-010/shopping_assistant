<script setup lang="ts">
import { BookOpen, MessageSquarePlus, PanelLeft } from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'

import { resetTransportCache } from '@/api/transport'
import ConversationColumn from '@/components/chat/ConversationColumn.vue'
import MetricChartPanel from '@/components/insights/MetricChartPanel.vue'
import MetricDefinitionPanel from '@/components/insights/MetricDefinitionPanel.vue'
import RecommendationPanel from '@/components/insights/RecommendationPanel.vue'
import ConversationDrawer from '@/components/layout/ConversationDrawer.vue'
import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import { useAppError } from '@/composables/useAppError'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

const authStore = useAuthStore()
const chatStore = useChatStore()
const { showError } = useAppError()

// 列表到达前没有可显示的商家名；给切换器一个占位文案，避免触发按钮空着。
const merchantLabel = computed(() => authStore.selected?.displayName ?? '加载中')

// 恢复商家失败或回退到默认商家都是用户需要知道的事，交给 F0 建立的全局提示区
// 呈现——Store 只负责产出文案，不自己找地方渲染。
watch(
  () => authStore.restoreNotice,
  (notice) => {
    if (notice) showError(notice)
  },
)

const isDrawerOpen = ref(false)
const drawerTrigger = ref<HTMLButtonElement | null>(null)

// fire-and-forget 调用必须在这里把失败接住：抛出去只会变成未处理的 Promise
// 拒绝，而抽屉照样显示「暂无历史会话」——把「加载失败」伪装成「没有历史」。
// loadConversations 本身仍然如实抛出，await 它的调用方需要那个异常。
function refreshConversations(): void {
  chatStore.loadConversations().catch(() => {
    showError('历史会话加载失败，请稍后重试。')
  })
}

function openDrawer(): void {
  // 每次打开都重新拉一次：刚问完的那轮会创建新会话，只在挂载时拉会漏掉它。
  refreshConversations()
  isDrawerOpen.value = true
}

function closeDrawer(): void {
  isDrawerOpen.value = false
  // 焦点归还给触发按钮——触发器在页头，不在抽屉组件内，只能由这里还。
  drawerTrigger.value?.focus()
}

onMounted(async () => {
  // 顺序不能并发：F3 起会话请求要带 Token，而 Token 是 restore() 才恢复出来的。
  // 并发发出去的话，会话请求会赶在身份就绪之前到达服务端，直接 401。
  // F2 的 Mock 不校验身份，所以这个顺序现在看不出差别——正因为看不出，更要现在就定死。
  await authStore.restore()
  refreshConversations()
})

function selectMerchant(displayName: string): void {
  // 仍然只在「合法且确实换了商家」时重置会话——F1 复查整改定下的行为，
  // 重复点当前商家不能把用户已有的对话清掉。
  if (displayName === authStore.selected?.displayName) return
  if (!authStore.displayNames.includes(displayName)) return

  authStore.selectByDisplayName(displayName)

  // 换商家等于换租户。当前对话、本地会话列表、Mock 里那张会话表都要一起丢掉，
  // 否则抽屉一打开就露出上一个商家的会话标题。
  // 注意这只是演示级隔离：真正的隔离必须由服务端按 Token 过滤（F3）。
  resetTransportCache()
  chatStore.reset()
  chatStore.clearConversations()
}

function startNewConversation(): void {
  chatStore.reset()
}
</script>

<template>
  <div class="assistant-shell">
    <a class="skip-link" href="#main-content">跳到对话主内容</a>
    <header class="assistant-header" data-testid="assistant-header">
      <button
        ref="drawerTrigger"
        class="header-icon-button header-nav-button"
        type="button"
        aria-label="打开对话目录"
        :aria-expanded="isDrawerOpen"
        @click="openDrawer"
      >
        <PanelLeft :size="19" aria-hidden="true" />
      </button>
      <img class="brand-logo" src="/borough-logo.svg" alt="Borough" width="50" height="40" />
      <div class="brand-title">
        <h1>Borough 商家 AI 助手</h1>
        <p>经营数据、分析与行动建议</p>
      </div>
      <MerchantSwitcher
        :model-value="merchantLabel"
        class="header-merchant-switcher"
        :merchants="authStore.displayNames"
        @update:model-value="selectMerchant"
      />
      <div class="header-actions">
        <RouterLink
          class="header-icon-button"
          to="/knowledge-base"
          aria-label="知识库维护"
          title="知识库维护"
        >
          <BookOpen :size="19" aria-hidden="true" />
        </RouterLink>
        <button class="new-chat-button" type="button" @click="startNewConversation">
          <MessageSquarePlus :size="18" aria-hidden="true" />
          <span>新会话</span>
        </button>
      </div>
    </header>

    <section class="workspace-grid" data-testid="workspace-grid">
      <aside
        class="workspace-side workspace-side-left"
        data-testid="workspace-column"
        aria-label="指标与洞察"
      >
        <MetricDefinitionPanel :answer="chatStore.currentAnswer" />
        <MetricChartPanel :answer="chatStore.currentAnswer" />
      </aside>

      <ConversationColumn id="main-content" data-testid="workspace-column" />

      <aside
        class="workspace-side workspace-side-right"
        data-testid="workspace-column"
        aria-label="行动建议"
      >
        <RecommendationPanel :answer="chatStore.currentAnswer" @ask="chatStore.submitMessage" />
      </aside>
    </section>

    <ConversationDrawer :open="isDrawerOpen" @close="closeDrawer" />
  </div>
</template>

<style scoped>
.assistant-shell {
  width: min(100%, 1500px);
  height: 100svh;
  min-height: 620px;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0 auto;
  padding: var(--space-3) var(--space-5) var(--space-4);
}

.skip-link {
  position: fixed;
  top: var(--space-2);
  left: var(--space-2);
  z-index: 100;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-control);
  color: #fff;
  background: var(--color-primary-strong);
  text-decoration: none;
  transform: translateY(-180%);
  transition: var(--transition-interactive);
}

.skip-link:focus-visible {
  transform: translateY(0);
}

.assistant-header {
  min-height: 54px;
  display: grid;
  /* 商家名不能被截断——Borough商家100/101/102 只差最后那位数字，截掉就等于
     无法确认当前身份。1440px 实测名称需要 107px，加状态点、箭头和内边距取 175px。 */
  grid-template-columns: 36px 50px minmax(0, 1fr) minmax(150px, 175px) auto;
  grid-template-areas: 'nav logo title merchant actions';
  align-items: center;
  gap: var(--space-2);
  flex: none;
}

.header-icon-button,
.new-chat-button {
  height: var(--control-height);
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  box-shadow: var(--shadow-control);
  text-decoration: none;
  transition: var(--transition-interactive);
}

.header-icon-button {
  width: 36px;
}

.header-nav-button {
  grid-area: nav;
}

.header-icon-button:hover,
.new-chat-button:hover {
  border-color: #cdd7fd;
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.brand-logo {
  grid-area: logo;
  width: 50px;
  height: 40px;
  border-radius: var(--radius-control);
  box-shadow: 0 7px 20px rgba(30, 41, 59, 0.13);
}

.brand-title {
  grid-area: title;
  min-width: 0;
}

.brand-title h1 {
  overflow: hidden;
  margin: 0;
  font-size: var(--font-size-page-title);
  font-weight: var(--font-weight-title);
  letter-spacing: -0.02em;
  line-height: 1.2;
  text-overflow: ellipsis;
  text-wrap: balance;
  white-space: nowrap;
}

.brand-title p {
  margin: var(--space-1) 0 0;
  /* 不用 --color-text-muted：#8a95a7 在本页背景上只有约 2.8-3.0:1，
     12px 正文需要 4.5:1。这个 token 只适合大字号或纯装饰。 */
  color: var(--color-text-secondary);
  font-size: var(--font-size-body);
}

.header-merchant-switcher {
  grid-area: merchant;
  min-width: 0;
}

.header-actions {
  grid-area: actions;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  white-space: nowrap;
}

.new-chat-button {
  grid-auto-flow: column;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-control);
}

.workspace-grid {
  min-height: 0;
  flex: 1;
  display: grid;
  grid-template-columns: minmax(230px, 280px) minmax(0, 760px) minmax(230px, 280px);
  grid-template-areas: 'left chat right';
  justify-content: center;
  gap: 14px;
}

.workspace-side {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  overflow: auto;
  scrollbar-color: #cbd4e2 transparent;
  scrollbar-width: thin;
}

.workspace-side-left {
  grid-area: left;
}

.workspace-side-right {
  grid-area: right;
}

.workspace-grid > :nth-child(2) {
  grid-area: chat;
}

@media (max-width: 1240px) {
  .workspace-grid {
    grid-template-columns: minmax(230px, 280px) minmax(0, 760px);
    grid-template-rows: minmax(0, 0.9fr) minmax(0, 1.1fr);
    grid-template-areas:
      'left chat'
      'right chat';
  }
}

@media (max-width: 860px) {
  .assistant-shell {
    height: auto;
    min-height: 100svh;
    padding: 10px 12px 18px;
  }

  .workspace-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
    grid-template-areas:
      'chat'
      'left'
      'right';
  }

  .workspace-grid > :nth-child(2) {
    height: calc(100svh - 80px);
    min-height: 560px;
  }

  .workspace-side {
    overflow: visible;
  }
}

@media (max-width: 560px) {
  .assistant-shell {
    padding-inline: 7px;
  }

  .assistant-header {
    grid-template-columns: 36px 43px minmax(0, 1fr) auto;
    grid-template-rows: 36px auto;
    grid-template-areas:
      'nav logo title actions'
      '. merchant merchant .';
    row-gap: 7px;
  }

  .brand-logo {
    width: 43px;
    height: 36px;
  }

  .brand-title h1 {
    font-size: 16px;
  }

  .brand-title p,
  .new-chat-button span {
    display: none;
  }

  .new-chat-button {
    width: 36px;
    padding: 0;
  }

  :deep(.header-merchant-switcher .merchant-switcher__trigger) {
    height: 32px;
  }

  :deep(.header-merchant-switcher .merchant-switcher__name) {
    font-size: 12px;
  }

  :deep(.header-merchant-switcher .merchant-switcher__menu) {
    right: auto;
    left: 0;
  }
}
</style>
