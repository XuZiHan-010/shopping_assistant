export const COLUMN_LABELS: Readonly<Record<string, string>> = {
  date: '营业日期',
  order_no: '订单号',
  order_status: '订单状态',
  paid_amount: '支付金额',
  gmv: '成交 GMV',
  return_count: '退货量',
}

export function columnLabel(key: string): string {
  return COLUMN_LABELS[key] ?? key
}
