<script setup lang="ts">
/**
 * 商品缩略图：地址由 `resolveProductImageSrc` 解析，无图、未配置顾客端地址或加载失败时显示占位。
 *
 * 纯装饰：商品名就在旁边，所以 `alt=""` 且占位不进读屏；「缺商品图片」由后端缺口标签表达，
 * 这里不据此判定任何缺口（R4/R7）。
 */
import { ImageOff } from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import { resolveProductImageSrc } from './productContent'

const props = defineProps<{ imageUrl: string | null }>()

const src = computed(() => resolveProductImageSrc(props.imageUrl))
const failed = ref(false)

watch(src, () => {
  failed.value = false
})
</script>

<template>
  <span class="thumb" data-test="product-thumb">
    <img
      v-if="src && !failed"
      :src="src"
      alt=""
      width="44"
      height="44"
      loading="lazy"
      decoding="async"
      referrerpolicy="no-referrer"
      @error="failed = true"
    />
    <ImageOff v-else :size="16" aria-hidden="true" data-test="product-thumb-empty" />
  </span>
</template>

<style scoped>
.thumb {
  display: grid;
  flex: none;
  place-items: center;
  width: 44px;
  height: 44px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--well);
  color: var(--ink-soft);
}

.thumb img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
