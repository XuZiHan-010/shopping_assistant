import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import { useAppError } from '@/composables/useAppError'

import App from './App.vue'

function buildRouter() {
  return createRouter({
    history: createWebHistory(),
    routes: [{ path: '/', component: { template: '<div data-testid="stub-route" />' } }],
  })
}

async function mountApp() {
  const router = buildRouter()
  const wrapper = mount(App, { global: { plugins: [router] } })
  await router.push('/')
  await router.isReady()
  return wrapper
}

beforeEach(() => {
  // 每个用例都从中文默认语言重新出发，避免上一条用例切换到英文后残留。
  i18n.global.locale.value = 'zh-CN'
  useAppError().clearError()
  document.head.innerHTML = '<link rel="icon" type="image/svg+xml" href="/borough-logo.svg" />'
})

afterEach(() => {
  document.head.innerHTML = ''
})

describe('App 全局错误横幅', () => {
  it('没有错误时不渲染横幅', async () => {
    const wrapper = await mountApp()

    expect(wrapper.find('.app-error').exists()).toBe(false)
  })

  it('中文模式下关闭按钮文案为「关闭」', async () => {
    useAppError().showError('出错了')
    const wrapper = await mountApp()

    expect(wrapper.get('.app-error button').text()).toBe('关闭')
  })

  it('英文模式下关闭按钮文案为 Close', async () => {
    i18n.global.locale.value = 'en-US'
    useAppError().showError('Something went wrong')
    const wrapper = await mountApp()

    expect(wrapper.get('.app-error button').text()).toBe('Close')
  })

  it('点击关闭按钮清空错误状态', async () => {
    useAppError().showError('出错了')
    const wrapper = await mountApp()

    await wrapper.get('.app-error button').trigger('click')

    expect(wrapper.find('.app-error').exists()).toBe(false)
  })
})

describe('App 按 locale 切换品牌 favicon', () => {
  it('英文模式下 favicon 指向英文资源', async () => {
    i18n.global.locale.value = 'en-US'
    await mountApp()

    const link = document.querySelector('link[rel="icon"]')
    expect(link?.getAttribute('href')).toBe('/borough-logo-en.svg')
  })

  it('中文模式下 favicon 指向中文资源', async () => {
    await mountApp()

    const link = document.querySelector('link[rel="icon"]')
    expect(link?.getAttribute('href')).toBe('/borough-logo.svg')
  })

  it('挂载后切换语言会同步更新 favicon', async () => {
    await mountApp()
    expect(document.querySelector('link[rel="icon"]')?.getAttribute('href')).toBe(
      '/borough-logo.svg',
    )

    i18n.global.locale.value = 'en-US'
    await Promise.resolve()

    expect(document.querySelector('link[rel="icon"]')?.getAttribute('href')).toBe(
      '/borough-logo-en.svg',
    )
  })
})

describe('品牌 SVG 资源的可访问标题', () => {
  it('中文资源 title 为 Borough 商家 AI 助手', () => {
    const svg = readFileSync(resolve(process.cwd(), 'public/borough-logo.svg'), 'utf-8')

    expect(svg).toMatch(/<title[^>]*>Borough 商家 AI 助手<\/title>/)
  })

  it('英文资源 title 为 Borough Merchant AI Assistant', () => {
    const svg = readFileSync(resolve(process.cwd(), 'public/borough-logo-en.svg'), 'utf-8')

    expect(svg).toMatch(/<title[^>]*>Borough Merchant AI Assistant<\/title>/)
  })
})
