/**
 * 商家经营只读面与草稿审批 Adapter（契约 §8.12.3、§8.13.3）。
 *
 * 两条边界写在这里，界面层不需要再记：
 *
 * 1. **审批证据是不透明串，原样回传**。它绑定了签发会话、草案版本与目标版本，
 *    界面不解析、不缓存、不跨会话复用；读到详情后应尽快提交，过期就重新读一次详情。
 * 2. **游标绑定查询形状**。换筛选条件或 `limit` 后必须从首页重新开始，
 *    拿旧游标继续翻会得到 `INVALID_CURSOR`（那不是可重试错误）。
 */
import type { components } from '@/api/generated'

import { merchantRequest, queryString } from './v2Http'

type RawAlertPage = components['schemas']['CursorPage_InventoryAlert_']
type RawAlert = components['schemas']['InventoryAlert']
type RawProductContentPage = components['schemas']['CursorPage_MerchantProductContent_']
type RawProductContent = components['schemas']['MerchantProductContent']
type RawMerchantCouponPage = components['schemas']['CursorPage_MerchantCoupon_']
type RawMerchantCoupon = components['schemas']['MerchantCoupon']
type RawDraftPage = components['schemas']['CursorPage_DraftSummary_']
type RawDraftSummary = components['schemas']['DraftSummary']
type RawDraftDetail = components['schemas']['DraftDetailResponse']
type RawApplyResponse = components['schemas']['DraftApplyResponse']
type RawBrief = components['schemas']['DailyBriefResponse']
type RawGuardrail = components['schemas']['GuardrailCheckResult']

export type InventoryAlertKind = RawAlert['kind']
export type DraftState = RawDraftSummary['state']
export type DraftKind = RawDraftSummary['kind']

export interface InventoryAlert {
  id: string
  kind: InventoryAlertKind
  productId: string
  productName: string
  stockOnHand: number
  stockReserved: number
  stockAvailable: number
  lowStockThreshold: number
  soldLast30d: number
  /** `null` 表示「未知 / 无近期销量」，不要在界面上显示成 0 天。 */
  daysOfSupply: number | null
}

export interface MerchantProductContent {
  id: string
  title: string
  category: string
  status: string
  /** 受控图片地址：`/demo/products/…` 相对顾客端站点，或白名单 HTTPS；无图或不可信为 `null`。 */
  imageUrl: string | null
  contentVersion: number
  missingRequiredAttributes: string[]
  missingContentFields: string[]
  contentComplete: boolean
  stockOnHand: number
  stockReserved: number
  stockAvailable: number
}

export interface MerchantCoupon {
  id: string
  name: string
  kind: RawMerchantCoupon['kind']
  state: string
  currentlyActive: boolean
  minSpendCents: number
  amountOffCents: number | null
  discountBps: number | null
  startsAt: string
  endsAt: string
}

export interface Page<T> {
  items: T[]
  nextCursor: string | null
  hasMore: boolean
}

export interface DraftSummary {
  id: string
  kind: DraftKind
  state: DraftState
  title: string
  draftVersion: number
  targetVersion: number
  createdAt: string
  updatedAt: string
  expiresAt: string
  /** 只有 `CONTENT_CHANGE` 批量起草的子草稿才非空；界面据此按批次分组展示。 */
  batchId: string | null
}

export interface GuardrailCheck {
  code: string
  passed: boolean
  currentLimit: string | null
  remediation: string | null
}

export interface DraftDiffEntry {
  entryId: string
  targetType: 'PRODUCT' | 'COUPON' | 'AFTER_SALE'
  targetId: string
  field: string
  unit: components['schemas']['DiffUnit']
  before: string | number | boolean | null
  after: string | number | boolean | null
  /** 应用时才计算的预览值，以应用结果为准。 */
  isPreview: boolean
}

export interface DraftDetail extends DraftSummary {
  diff: DraftDiffEntry[]
  /** 起草时的护栏快照，仅供展示；应用时会按当时生效的配置重查。 */
  guardrailChecks: GuardrailCheck[]
  guardrailsCheckedAt: string
  /** 仅 `STAGED` 草稿有值；一次性、≤10 分钟有效。 */
  approvalEvidence: string | null
  approvalEvidenceExpiresAt: string | null
}

export interface DailyBriefItem {
  rank: number
  kind: components['schemas']['DailyBriefItemKind']
  title: string
  evidence: string
  amountCents: number | null
  /** 只把问题填进输入框，不代为发送、批准或执行。 */
  nextActionPrompt: string | null
}

export interface DailyBrief {
  briefVersion: number
  businessDate: string
  businessTimezone: string
  dataAsOf: string
  generatedAt: string
  trigger: 'SCHEDULED' | 'REGENERATED'
  items: DailyBriefItem[]
  collapsedCount: number
  degraded: boolean
  degradedReason: string | null
  analysisSources: { source: string; degraded: boolean; degradedReason: string | null }[]
}

export interface ApplyDraftInput {
  clientRequestId: string
  draftVersion: number
  targetVersion: number
  approvalEvidence: string
  acceptedEntryIds?: string[]
}

export interface AppliedDraft {
  draft: DraftSummary
  ledgerEntry: {
    id: string
    draftId: string
    draftedBy: { actorType: 'AGENT' | 'MERCHANT'; label: string }
    approvedBy: { actorType: 'AGENT' | 'MERCHANT'; label: string }
    approvedAt: string
    appliedEntryIds: string[]
    guardrailResults: GuardrailCheck[]
  }
}

function toAlert(raw: RawAlert): InventoryAlert {
  return {
    id: raw.id,
    kind: raw.kind,
    productId: raw.product_id,
    productName: raw.product_name,
    stockOnHand: raw.stock_on_hand,
    stockReserved: raw.stock_reserved,
    stockAvailable: raw.stock_available,
    lowStockThreshold: raw.low_stock_threshold,
    soldLast30d: raw.sold_last_30d,
    daysOfSupply: raw.days_of_supply,
  }
}

function toSummary(raw: RawDraftSummary): DraftSummary {
  return {
    id: raw.id,
    kind: raw.kind,
    state: raw.state,
    title: raw.title,
    draftVersion: raw.draft_version,
    targetVersion: raw.target_version,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
    expiresAt: raw.expires_at,
    batchId: raw.batch_id ?? null,
  }
}

function toGuardrail(raw: RawGuardrail): GuardrailCheck {
  return {
    code: raw.code,
    passed: raw.passed,
    currentLimit: raw.current_limit,
    remediation: raw.remediation,
  }
}

export async function fetchInventoryAlerts(
  sessionId: string,
  options: { cursor?: string | null; limit?: number; kind?: InventoryAlertKind } = {},
): Promise<Page<InventoryAlert>> {
  const query = queryString({
    cursor: options.cursor,
    limit: options.limit,
    kind: options.kind,
  })
  const response = await merchantRequest(`/api/v2/merchant/inventory/alerts${query}`, sessionId)
  const payload = (await response.json()) as RawAlertPage
  return {
    items: payload.items.map(toAlert),
    nextCursor: payload.next_cursor,
    hasMore: payload.has_more,
  }
}

export async function fetchMerchantProductContent(
  sessionId: string,
  options: { cursor?: string | null; limit?: number } = {},
): Promise<Page<MerchantProductContent>> {
  const response = await merchantRequest(
    `/api/v2/merchant/products/content${queryString(options)}`,
    sessionId,
  )
  const payload = (await response.json()) as RawProductContentPage
  return {
    items: payload.items.map((raw: RawProductContent) => ({
      id: raw.id,
      title: raw.title,
      category: raw.category,
      status: raw.status,
      imageUrl: raw.image_url,
      contentVersion: raw.content_version,
      missingRequiredAttributes: raw.missing_required_attributes,
      missingContentFields: raw.missing_content_fields,
      contentComplete: raw.content_complete,
      stockOnHand: raw.stock_on_hand,
      stockReserved: raw.stock_reserved,
      stockAvailable: raw.stock_available,
    })),
    nextCursor: payload.next_cursor,
    hasMore: payload.has_more,
  }
}

export async function fetchMerchantCoupons(
  sessionId: string,
  options: { cursor?: string | null; limit?: number } = {},
): Promise<Page<MerchantCoupon>> {
  const response = await merchantRequest(
    `/api/v2/merchant/coupons${queryString(options)}`,
    sessionId,
  )
  const payload = (await response.json()) as RawMerchantCouponPage
  return {
    items: payload.items.map((raw: RawMerchantCoupon) => ({
      id: raw.id,
      name: raw.name,
      kind: raw.kind,
      state: raw.state,
      currentlyActive: raw.currently_active,
      minSpendCents: raw.min_spend_cents,
      amountOffCents: raw.amount_off_cents,
      discountBps: raw.discount_bps,
      startsAt: raw.starts_at,
      endsAt: raw.ends_at,
    })),
    nextCursor: payload.next_cursor,
    hasMore: payload.has_more,
  }
}

export async function fetchDrafts(
  sessionId: string,
  options: {
    cursor?: string | null
    limit?: number
    state?: DraftState
    kind?: DraftKind
    batchId?: string
  } = {},
): Promise<Page<DraftSummary>> {
  const query = queryString({
    cursor: options.cursor,
    limit: options.limit,
    state: options.state,
    kind: options.kind,
    batch_id: options.batchId,
  })
  const response = await merchantRequest(`/api/v2/merchant/drafts${query}`, sessionId)
  const payload = (await response.json()) as RawDraftPage
  return {
    items: payload.items.map(toSummary),
    nextCursor: payload.next_cursor,
    hasMore: payload.has_more,
  }
}

/** 读取详情即签发一枚新的一次性审批证据；不要缓存返回值。 */
export async function fetchDraftDetail(sessionId: string, draftId: string): Promise<DraftDetail> {
  const response = await merchantRequest(
    `/api/v2/merchant/drafts/${encodeURIComponent(draftId)}`,
    sessionId,
  )
  const payload = (await response.json()) as RawDraftDetail
  return {
    ...toSummary(payload),
    diff: payload.diff.entries.map((entry) => ({
      entryId: entry.entry_id,
      targetType: entry.target_type,
      targetId: entry.target_id,
      field: entry.field,
      unit: entry.unit,
      before: entry.before,
      after: entry.after,
      isPreview: entry.is_preview,
    })),
    guardrailChecks: payload.guardrail_checks.map(toGuardrail),
    guardrailsCheckedAt: payload.guardrails_checked_at,
    approvalEvidence: payload.approval_evidence,
    approvalEvidenceExpiresAt: payload.approval_evidence_expires_at,
  }
}

/**
 * 批准并应用一份草稿。
 *
 * 失败的语义分三类，界面要分开处理：`VERSION_CONFLICT` 要重新读详情再确认，
 * `GUARDRAIL_REJECTED` 要改方案，`CONFIRMATION_REQUIRED` 要重新读详情取新证据。
 * 三者都 `retryable=false`——原样重发同一个请求不会成功。
 */
export async function applyDraft(
  sessionId: string,
  draftId: string,
  input: ApplyDraftInput,
): Promise<AppliedDraft> {
  const response = await merchantRequest(
    `/api/v2/merchant/drafts/${encodeURIComponent(draftId)}/apply`,
    sessionId,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_request_id: input.clientRequestId,
        draft_version: input.draftVersion,
        target_version: input.targetVersion,
        approval_evidence: input.approvalEvidence,
        ...(input.acceptedEntryIds ? { accepted_entry_ids: input.acceptedEntryIds } : {}),
      }),
    },
  )
  const payload = (await response.json()) as RawApplyResponse
  const entry = payload.ledger_entry
  return {
    draft: toSummary(payload.draft),
    ledgerEntry: {
      id: entry.id,
      draftId: entry.draft_id,
      draftedBy: { actorType: entry.drafted_by.actor_type, label: entry.drafted_by.label },
      approvedBy: { actorType: entry.approved_by.actor_type, label: entry.approved_by.label },
      approvedAt: entry.approved_at,
      appliedEntryIds: entry.applied_entry_ids,
      guardrailResults: entry.guardrail_results.map(toGuardrail),
    },
  }
}

/** 丢弃草稿；已丢弃的重复调用仍然成功（DELETE 天然幂等）。 */
export async function discardDraft(sessionId: string, draftId: string): Promise<void> {
  await merchantRequest(`/api/v2/merchant/drafts/${encodeURIComponent(draftId)}`, sessionId, {
    method: 'DELETE',
  })
}

function toBrief(payload: RawBrief): DailyBrief {
  return {
    briefVersion: payload.brief_version,
    businessDate: payload.business_date,
    businessTimezone: payload.business_timezone,
    dataAsOf: payload.data_as_of,
    generatedAt: payload.generated_at,
    trigger: payload.trigger,
    items: (payload.items ?? []).map((item) => ({
      rank: item.rank,
      kind: item.kind,
      title: item.title,
      evidence: item.evidence,
      amountCents: item.amount_cents,
      nextActionPrompt: item.next_action_prompt,
    })),
    collapsedCount: payload.collapsed_count,
    degraded: payload.degraded,
    degradedReason: payload.degraded_reason,
    analysisSources: payload.analysis_sources.map((entry) => ({
      source: entry.source,
      degraded: entry.degraded,
      degradedReason: entry.degraded_reason,
    })),
  }
}

export async function fetchDailyBrief(sessionId: string): Promise<DailyBrief> {
  const response = await merchantRequest('/api/v2/merchant/briefs/daily/current', sessionId)
  const payload = (await response.json()) as RawBrief
  return toBrief(payload)
}

/**
 * D18⑨：限流重新生成——冷却期内的请求转成 `RATE_LIMITED`（可重试）；
 * 同一 `clientRequestId` 重放直接回放首次结果，不重复生成新版本（§8.7.3）。
 */
export async function regenerateDailyBrief(
  sessionId: string,
  clientRequestId: string,
): Promise<DailyBrief> {
  const response = await merchantRequest(
    '/api/v2/merchant/briefs/daily/current/regenerate',
    sessionId,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_request_id: clientRequestId }),
    },
  )
  const payload = (await response.json()) as RawBrief
  return toBrief(payload)
}
