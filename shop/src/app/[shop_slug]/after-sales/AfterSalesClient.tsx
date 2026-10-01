'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  confirmAfterSale, getAfterSale, listAfterSales, previewAfterSale, supplementAfterSale,
  type AfterSaleCreateInput,
} from '@/api/afterSalesApi'
import { ApiError } from '@/api/errors'
import { getOrder } from '@/api/shopApi'
import { formatPrice } from '@/lib/format'
import type { AfterSaleChallenge, AfterSaleDetail, AfterSaleSummary, AfterSaleType } from '@/types/afterSales'
import type { Order } from '@/types/shop'
import '@/views/storefront-views.css'

const TYPE_LABEL: Record<AfterSaleType, string> = {
  RETURN_REFUND: '退货退款', REFUND_ONLY: '仅退款', TICKET: '客服工单',
}
const TYPE_LABEL_EN: Record<AfterSaleType, string> = {
  RETURN_REFUND: 'Return and refund', REFUND_ONLY: 'Refund only', TICKET: 'Support ticket',
}

const STATE_LABEL: Record<AfterSaleSummary['state'], string> = {
  PENDING_MERCHANT: '待商家处理', APPROVED: '已同意', REJECTED: '已拒绝',
  AWAITING_RETURN: '待寄回', RECEIVED: '商家已收货', REFUNDED: '已退款',
  AWAITING_CUSTOMER_INFO: '待补充信息', CLOSED: '已关闭',
}
const STATE_LABEL_EN: Record<AfterSaleSummary['state'], string> = {
  PENDING_MERCHANT: 'Pending merchant', APPROVED: 'Approved', REJECTED: 'Rejected',
  AWAITING_RETURN: 'Awaiting return', RECEIVED: 'Return received', REFUNDED: 'Refunded',
  AWAITING_CUSTOMER_INFO: 'Awaiting customer information', CLOSED: 'Closed',
}

function closureLabel(detail: AfterSaleDetail, english: boolean): string {
  const last = [...detail.events].reverse().find((event) => event.actor !== 'SYSTEM')
  if (last?.toState === 'REFUNDED') return english ? 'Closed after refund' : '已退款结案'
  if (last?.toState === 'REJECTED') return english ? 'Closed after rejection' : '已拒绝结案'
  return english ? 'Closed after resolution' : '已处理结案'
}

const INELIGIBLE_RULE_EN: Record<string, string> = {
  ORDER_NOT_DELIVERED: 'This order is not eligible for the selected request type yet.',
  WINDOW_EXPIRED: 'Requests must be made within 7 days after delivery.',
  ALREADY_IN_PROGRESS: 'This order already has an active after-sales request.',
  ALREADY_REFUNDED: 'These items have no remaining refundable amount.',
}

function previewError(error: unknown, english: boolean): string {
  if (error instanceof ApiError && error.code === 'GUARDRAIL_REJECTED') {
    const detail = error.details[0]
    if (english) {
      const reason = detail?.reason
      return typeof reason === 'string' && INELIGIBLE_RULE_EN[reason]
        ? INELIGIBLE_RULE_EN[reason]
        : 'This request is not eligible under the current platform rule.'
    }
    if (typeof detail?.rule_reference === 'string') return detail.rule_reference
  }
  return english
    ? 'Preview failed. Check the order and reason, then retry.'
    : '预检暂时失败，请核对订单和申请原因后重试'
}

export function AfterSalesClient({ orderId, caseId, locale = 'zh-CN' }: { orderId?: string; caseId?: string; locale?: 'zh-CN' | 'en-US' }) {
  const english = locale === 'en-US'
  const copy = (zh: string, en: string) => english ? en : zh
  const types = english ? TYPE_LABEL_EN : TYPE_LABEL
  const states = english ? STATE_LABEL_EN : STATE_LABEL
  const [order, setOrder] = useState<Order | null>(null)
  const [items, setItems] = useState<AfterSaleSummary[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [type, setType] = useState<AfterSaleType>('REFUND_ONLY')
  const [reason, setReason] = useState('')
  const [includeSummary, setIncludeSummary] = useState(false)
  const [challenge, setChallenge] = useState<AfterSaleChallenge | null>(null)
  const [prepared, setPrepared] = useState<AfterSaleCreateInput | null>(null)
  const [consented, setConsented] = useState(false)
  const [detail, setDetail] = useState<AfterSaleDetail | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<'INCLUDED' | 'NOT_SHARED' | 'UNAVAILABLE' | null>(null)
  const requestId = useRef<string | null>(null)
  const supplementId = useRef<string | null>(null)

  const refresh = useCallback(async () => setItems(await listAfterSales()), [])
  useEffect(() => {
    void listAfterSales().then(setItems).catch(() => setError(
      english ? 'Could not load after-sales cases.' : '暂时无法加载售后记录'))
  }, [english])
  useEffect(() => {
    if (!orderId) return
    void getOrder(orderId).then((value) => {
      setOrder(value)
      setSelected(value.items.map((item) => item.orderItemId))
    }).catch(() => setError(english ? 'Could not load order.' : '暂时无法加载订单'))
  }, [orderId, english])
  useEffect(() => {
    if (!caseId) return
    void getAfterSale(caseId).then(setDetail).catch(() => setError(
      english ? 'Could not load case details.' : '暂时无法加载售后详情'))
  }, [caseId, english])

  function changeInput() {
    setChallenge(null)
    setPrepared(null)
    setConsented(false)
    requestId.current = null
  }

  async function preview() {
    if (!orderId || !order || !selected.length) return
    setBusy(true)
    setError(null)
    requestId.current ??= crypto.randomUUID()
    const input: AfterSaleCreateInput = {
      clientRequestId: requestId.current, orderId, type,
      orderItemIds: selected, reason, includeConversationSummary: includeSummary,
    }
    try {
      setChallenge(await previewAfterSale(input))
      setPrepared(input)
    } catch (caught) {
      setError(previewError(caught, english))
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    if (!challenge || !prepared || !consented) return
    setBusy(true)
    setError(null)
    try {
      await confirmAfterSale(prepared, challenge.token)
      setSuccess(challenge.summaryStatus)
      setChallenge(null)
      setPrepared(null)
      requestId.current = null
      await refresh()
    } catch {
      // 网络重试沿用同一请求 ID 与证据；过期证据可回到预览重新签发。
      setError(copy('提交未确认，请重试；同一申请不会重复创建', 'Submission was not confirmed. Retry with the same request.'))
    } finally {
      setBusy(false)
    }
  }

  async function open(id: string) {
    setError(null)
    try {
      setDetail(await getAfterSale(id))
      setNote('')
      supplementId.current = null
    } catch {
      setError(copy('暂时无法加载售后详情', 'Could not load case details.'))
    }
  }

  async function supplement() {
    if (!detail || detail.state !== 'AWAITING_CUSTOMER_INFO' || !note.trim()) return
    setBusy(true)
    setError(null)
    supplementId.current ??= crypto.randomUUID()
    try {
      await supplementAfterSale(detail.id, note.trim(), supplementId.current)
      supplementId.current = null
      await open(detail.id)
      await refresh()
    } catch {
      setError(copy('补充说明未确认，请重试；同一内容不会重复提交', 'Supplement was not confirmed. Retry with the same request.'))
    } finally {
      setBusy(false)
    }
  }

  return <main className="stack ws-after-sales">
    <h1>{copy('售后服务', 'After-sales service')}</h1>
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    {success && <p className="notice">{copy('申请已提交。', 'Request submitted. ')}{success === 'INCLUDED'
      ? copy('这段对话已随申请提交给商家。', 'The conversation summary was shared with the merchant.')
      : success === 'UNAVAILABLE' ? copy('对话摘要暂不可用，商家将查看申请并处理。', 'The conversation summary is unavailable; the merchant can still review the request.')
        : copy('商家将查看申请并处理。', 'The merchant will review the request.')}</p>}

    {order && <section className="card card-body stack ws-after-sales-card" aria-label={copy('发起售后', 'Start an after-sales request')}>
      <h2>{copy('订单', 'Order')} {order.id}</h2>
      <label>{copy('售后类型', 'Request type')}
        <select value={type} onChange={(event) => { changeInput(); setType(event.target.value as AfterSaleType) }}>
          {Object.entries(types).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <fieldset><legend>{copy('选择商品', 'Select products')}</legend>
        {order.items.map((item) => <label key={item.orderItemId} className="row">
          <input type="checkbox" checked={selected.includes(item.orderItemId)} onChange={(event) => {
            changeInput()
            setSelected((current) => event.target.checked
              ? [...current, item.orderItemId]
              : current.filter((id) => id !== item.orderItemId))
          }} />
          {item.name}
        </label>)}
      </fieldset>
      <label>{copy('申请原因', 'Request reason')}
        <textarea aria-label={copy('申请原因', 'Request reason')} value={reason} maxLength={1000} onChange={(event) => {
          changeInput(); setReason(event.target.value)
        }} />
      </label>
      <label className="row">
        <input type="checkbox" checked={includeSummary} onChange={(event) => {
          changeInput(); setIncludeSummary(event.target.checked)
        }} />
        {copy('将相关对话摘要随申请提交给商家', 'Share a summary of related conversations with the merchant')}
      </label>
      <button className="btn" disabled={busy || selected.length === 0 || (type === 'TICKET' && !reason.trim())} onClick={() => void preview()}>
        {copy('预览申请', 'Preview request')}
      </button>
      {challenge && <section className="notice stack" aria-label={copy('申请核对', 'Review request')}>
        <h3>{copy('请核对申请', 'Review your request')}</h3>
        <p>{types[type]}：{challenge.reason || copy('未填写原因', 'No reason provided')}</p>
        <ul>{challenge.lines.map((line) => <li key={line.orderItemId}>{line.name} × {line.quantity}</li>)}</ul>
        {challenge.estimatedRefundCents !== null && <p>{copy('后端计算的预计可退金额', 'Estimated refund calculated by the service')}：{formatPrice(challenge.estimatedRefundCents)}</p>}
        {challenge.summaryStatus === 'INCLUDED' && <p>{copy('随单对话摘要', 'Shared conversation summary')}：{challenge.conversationSummary}</p>}
        {challenge.summaryStatus === 'UNAVAILABLE' && <p>{copy('随单对话摘要暂不可用，申请仍可继续。', 'The conversation summary is unavailable. You can still submit the request.')}</p>}
        <label className="row"><input type="checkbox" checked={consented} onChange={(event) => setConsented(event.target.checked)} />{copy('我已核对申请信息', 'I have reviewed the request')}</label>
        <button className="btn btn-primary" disabled={!consented || busy} onClick={() => void confirm()}>{copy('确认提交', 'Submit request')}</button>
      </section>}
    </section>}

    <section className="card card-body stack ws-after-sales-card" aria-label={copy('我的售后', 'My after-sales cases')}>
      <h2>{copy('我的售后', 'My after-sales cases')}</h2>
      {items.length === 0 && <p className="muted">{copy('暂无售后记录', 'No after-sales cases yet')}</p>}
      {items.map((item) => <button key={item.id} className="btn" onClick={() => void open(item.id)}>
        {types[item.type]} · {states[item.state]} · {item.orderId}
      </button>)}
    </section>

    {detail && <section className="card card-body stack ws-after-sales-card" aria-label={copy('售后详情', 'Case details')}>
      <h2>{copy('售后详情', 'Case details')}</h2>
      <p>{types[detail.type]} · {states[detail.state]}</p>
      {detail.reason && <p>{copy('申请原因', 'Request reason')}：{detail.reason}</p>}
      {detail.state === 'CLOSED' && <p>{closureLabel(detail, english)}</p>}
      {detail.refundAmountCents !== null && <p>{copy('可退金额', 'Refund amount')}：{formatPrice(detail.refundAmountCents)}</p>}
      {detail.conversationSummaryShared && <p>{copy('这段对话已随申请提交给商家。', 'The conversation summary was shared with the merchant.')}</p>}
      <h3>{copy('处理进度', 'Progress')}</h3>
      <ol>{detail.events.map((event) => <li key={event.id}>{states[event.toState]} · {new Date(event.occurredAt).toLocaleString(locale)}</li>)}</ol>
      {detail.supplements.length > 0 && <><h3>{copy('补充说明', 'Supplements')}</h3><ul>{detail.supplements.map((item) => <li key={item.id}>{item.note}</li>)}</ul></>}
      {detail.replies.length > 0 && <><h3>{copy('商家回复', 'Merchant replies')}</h3><ul>{detail.replies.map((item) => <li key={item.id}>{item.text}</li>)}</ul></>}
      {detail.state === 'AWAITING_CUSTOMER_INFO' && <div className="stack">
        <label>{copy('补充说明', 'Supplement')}
          <textarea value={note} maxLength={1000} onChange={(event) => {
            setNote(event.target.value); supplementId.current = null
          }} />
        </label>
        <button className="btn btn-primary" disabled={!note.trim() || busy} onClick={() => void supplement()}>{copy('提交补充说明', 'Submit supplement')}</button>
      </div>}
    </section>}
  </main>
}
