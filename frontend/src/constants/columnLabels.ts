import type { SupportedLocale } from '@/i18n'

const COLUMN_LABELS_BY_LOCALE: Readonly<Record<SupportedLocale, Readonly<Record<string, string>>>> =
  {
    'zh-CN': {
      date: '营业日期',
      order_no: '订单号',
      order_status: '订单状态',
      paid_amount: '支付金额',
      gmv: '成交 GMV',
      return_count: '退货量',
    },
    'en-US': {
      date: 'Business date',
      order_no: 'Order no.',
      order_status: 'Order status',
      paid_amount: 'Paid amount',
      gmv: 'GMV',
      return_count: 'Return count',
    },
  }

/** 明细表表头：已知列名按当前展示语言取本地化标签，未知列名原样透传（技术字段）。 */
export function columnLabel(key: string, locale: SupportedLocale): string {
  return COLUMN_LABELS_BY_LOCALE[locale][key] ?? key
}
