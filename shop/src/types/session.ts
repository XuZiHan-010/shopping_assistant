export interface ShopSession {
  sessionId: string
  shopSlug: string
  /** 已绑定演示顾客身份；未绑定即匿名访客。 */
  isBound: boolean
  expiresAt: string
}

export interface BindResult {
  /** 合并购物车时有商品因售罄或数量上限被调整（PRD C3，E9）。 */
  cartAdjusted: boolean
}
