import type { Locale } from './locale'
const names: Record<string, readonly [string, string]> = {
  search_products: ['搜索商品', 'Search products'], get_product: ['查看商品详情', 'View product'],
  get_product_attribute: ['查询商品属性', 'Look up product attributes'], get_shop_policy: ['查询店铺规则', 'Look up store policy'],
  set_cart_item: ['调整购物车', 'Update cart'], check_after_sale_eligibility: ['判定售后资格', 'Check return eligibility'],
  prepare_after_sale: ['准备售后申请', 'Prepare return request'], recall_preferences: ['读取偏好', 'Recall preferences'],
  get_my_order: ['查询订单', 'Look up order'],
}
export function toolDisplayName(toolName: string, locale: Locale): string { return names[toolName]?.[locale === 'en-US' ? 1 : 0] ?? toolName }
