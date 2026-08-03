<script setup lang="ts">
import { BookOpen, MessageSquarePlus, PanelLeft } from '@lucide/vue'
import { ref } from 'vue'

import ConversationColumn from '@/components/chat/ConversationColumn.vue'
import MerchantSwitcher from '@/components/layout/MerchantSwitcher.vue'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()

// F1 仅为视觉与切换交互提供展示名；F2 将由 Auth Store 的演示商家列表替换。
const merchantOptions = ['Borough商家100', 'Borough商家101', 'Borough商家102'] as const
const selectedMerchant = ref<(typeof merchantOptions)[number]>(merchantOptions[0])

function selectMerchant(merchant: string): void {
  if (!merchantOptions.includes(merchant as (typeof merchantOptions)[number])) return
  if (merchant === selectedMerchant.value) return

  selectedMerchant.value = merchant as (typeof merchantOptions)[number]
  chatStore.reset()
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
        class="header-icon-button header-nav-button"
        type="button"
        aria-label="打开对话目录"
        title="对话目录将在后续版本提供"
      >
        <PanelLeft :size="19" aria-hidden="true" />
      </button>
      <img class="brand-logo" src="/borough-logo.svg" alt="Borough" width="50" height="40" />
      <div class="brand-title">
        <h1>Borough 商家 AI 助手</h1>
        <p>经营数据、分析与行动建议</p>
      </div>
      <MerchantSwitcher
        :model-value="selectedMerchant"
        class="header-merchant-switcher"
        :merchants="merchantOptions"
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
        <div class="side-empty">
          <span>指标洞察</span>
          <p>发起指标类问题后，这里会显示指标口径和图表。</p>
        </div>
      </aside>

      <ConversationColumn id="main-content" data-testid="workspace-column" />

      <aside
        class="workspace-side workspace-side-right"
        data-testid="workspace-column"
        aria-label="行动建议"
      >
        <div class="side-empty">
          <span>行动建议</span>
          <p>基于经营数据的建议和后续问题会显示在这里。</p>
        </div>
      </aside>
    </section>
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
  grid-template-columns: 36px 50px minmax(0, 1fr) minmax(118px, 145px) auto;
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
  color: var(--color-text-muted);
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

.side-empty {
  min-height: 150px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  border: 1px dashed #dbe2ed;
  border-radius: 11px;
  color: var(--color-text-muted);
  background: rgba(250, 251, 254, 0.82);
  text-align: center;
}

.side-empty span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-control);
  font-weight: var(--font-weight-emphasis);
}

.side-empty p {
  max-width: 210px;
  margin: var(--space-2) 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-size-caption);
  line-height: var(--line-height-body);
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
