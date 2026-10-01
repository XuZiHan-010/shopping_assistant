<script setup lang="ts">
/**
 * 首页（W Task 8，设计说明 §2.2，PRD M1「经营」区）自上而下：
 * 问候 → 今日简报（含「去审批（N）」）→ 主指标面板 → 需要你处理 + 最近订单。
 *
 * 四个区块各自取数、各自降级，互不连坐；取数都推迟到浏览器空闲之后，首屏只有
 * 外壳与区块骨架（首屏门禁 `e2e/first-paint.spec.ts` 的请求序列保持不变）。
 * 原型里的「助手发现」没有独立数据来源，不实施（设计说明 §3.3）。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import HomeAttention from '@/components/home/HomeAttention.vue'
import HomeBriefCard from '@/components/home/HomeBriefCard.vue'
import HomeMetricPanel from '@/components/home/HomeMetricPanel.vue'
import HomeRecentOrders from '@/components/home/HomeRecentOrders.vue'
import { useAuthStore } from '@/stores/auth'
import { useLocaleStore } from '@/stores/locale'

const { t } = useI18n()
const auth = useAuthStore()
const localeStore = useLocaleStore()

/** 问候按浏览器本地时间；只影响一句寒暄，不参与任何业务日期计算。 */
const now = new Date()

const dateLabel = computed(() =>
  new Intl.DateTimeFormat(localeStore.locale, {
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  }).format(now),
)

const greeting = computed(() => {
  const hour = now.getHours()
  const key = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening'
  const text = t(`home.greeting.${key}`)
  const name = auth.selected?.displayName
  return name ? t('home.greetingWithName', { greeting: text, name }) : text
})
</script>

<template>
  <section class="home" :aria-label="t('pages.home.title')">
    <header class="home__head">
      <p class="home__date">{{ dateLabel }}</p>
      <h1 class="home__greeting" translate="no">{{ greeting }}</h1>
    </header>

    <HomeBriefCard />
    <HomeMetricPanel />

    <div class="home__grid">
      <HomeAttention />
      <HomeRecentOrders />
    </div>
  </section>
</template>

<style scoped>
.home {
  max-width: 1160px;
  margin: 0 auto;
  padding: 30px 36px 56px;
}

.home__head {
  margin-bottom: 20px;
}

.home__date {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  letter-spacing: 0.1em;
  color: var(--ink-soft);
}

.home__date::after {
  content: '';
  width: 42px;
  height: 1px;
  background: var(--gilt);
}

.home__greeting {
  margin: 0;
  font-family: var(--font-display);
  font-size: clamp(26px, 2.6vw, 32px);
  font-weight: 600;
  letter-spacing: -0.015em;
  line-height: 1.15;
  overflow-wrap: anywhere;
}

.home__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
  margin-top: 16px;
}

@media (max-width: 1280px) {
  .home__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 820px) {
  .home {
    padding: 18px 16px 40px;
  }

  .home__greeting {
    font-size: 22px;
  }
}
</style>
