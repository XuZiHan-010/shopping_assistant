export interface QuickQuestion {
  readonly category: string
  readonly question: string
}

/** 欢迎卡片的产品入口；不依赖 Mock 或后端返回。 */
export const QUICK_QUESTIONS = [
  { category: '趋势分析', question: '最近7天退货量趋势' },
  { category: '经营指标', question: '昨天总 GMV 是多少？' },
  { category: '业务明细', question: '查看最近订单明细' },
  { category: '规则问答', question: '我要货品上架，具体规则有吗？' },
] as const satisfies readonly QuickQuestion[]
