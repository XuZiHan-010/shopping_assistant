import { beforeEach, expect, it, vi } from 'vitest'
import AssistantPage from './assistant/page'
import CartPage from './cart/page'
import MemoriesPage from './memories/page'

const navigation = vi.hoisted(() => ({ redirect: vi.fn() }))
vi.mock('next/navigation', () => navigation)

beforeEach(() => navigation.redirect.mockReset())

const params = Promise.resolve({ shop_slug: 'borough-100' })

it.each([
  ['assistant', AssistantPage, '/borough-100'],
  ['cart', CartPage, '/borough-100?panel=cart'],
  ['memories', MemoriesPage, '/borough-100?panel=memory'],
] as const)('旧路由 /%s 重定向到新外壳', async (_name, page, target) => {
  await page({ params })
  expect(navigation.redirect).toHaveBeenCalledWith(target)
})
