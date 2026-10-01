/** wire（generated.ts，snake_case）→ 领域模型（camelCase）。组件永远不直接消费 generated.ts。 */
import type {
  Cart,
  Coupon,
  FulfillmentEvent,
  Order,
  OrderSummaryView,
  Product,
  ProductAttribute,
  ProductDetail,
  StoreProfile,
} from '@/types/shop'
import type { components } from '../generated'

type S = components['schemas']

export function toStoreProfile(raw: S['StoreProfileResponse']): StoreProfile {
  return { shopSlug: raw.shop_slug, displayName: raw.display_name, rulesSummary: raw.rules_summary }
}

export function toProduct(raw: S['ProductSummary']): Product {
  return {
    id: raw.id,
    name: raw.name,
    shortDescription: raw.short_description,
    priceCents: raw.price_cents,
    stockBand: raw.stock_band,
    imageUrl: raw.image_url,
    sourceLocale: raw.source_locale,
    contentVersion: raw.content_version,
    requestedLocale: raw.requested_locale,
    nameTranslationStatus: raw.name_translation_status,
    shortDescriptionTranslationStatus: raw.short_description_translation_status,
    category: raw.category,
  }
}

function toAttribute(raw: S['ProductAttribute']): ProductAttribute {
  const value = raw.value.trim()
  return {
    name: raw.name, value: value === '' ? null : raw.value, source: raw.source,
    nameTranslationStatus: raw.name_translation_status,
    valueTranslationStatus: raw.value_translation_status,
  }
}

export function toProductDetail(raw: S['ProductDetailResponse']): ProductDetail {
  return {
    ...toProduct(raw),
    description: raw.description,
    missingAttributes: raw.missing_attributes,
    attributes: raw.attributes.map(toAttribute),
    descriptionTranslationStatus: raw.description_translation_status,
  }
}

export function toCoupon(raw: S['CouponSummary']): Coupon {
  return {
    id: raw.id,
    name: raw.name,
    kind: raw.kind,
    minSpendCents: raw.min_spend_cents,
    amountOffCents: raw.amount_off_cents,
    discountBps: raw.discount_bps,
    productIds: raw.product_ids,
    startsAt: raw.starts_at,
    endsAt: raw.ends_at,
  }
}

export function toCart(raw: S['CartResponse']): Cart {
  return {
    subtotalCents: raw.subtotal_cents,
    items: raw.items.map((item) => ({
      productId: item.product_id,
      name: item.name,
      imageUrl: item.image_url,
      quantity: item.quantity,
      unitPriceCents: item.unit_price_cents,
      lineTotalCents: item.line_total_cents,
      stockBand: item.stock_band,
    })),
  }
}

export function toOrderSummary(raw: S['OrderSummary']): OrderSummaryView {
  return {
    id: raw.id,
    paymentStatus: raw.payment_status,
    fulfillmentStatus: raw.fulfillment_status,
    afterSaleStatus: raw.after_sale_status,
    totalCents: raw.total_cents,
    itemCount: raw.item_count,
    createdAt: raw.created_at,
    payBy: raw.pay_by,
    leadItem: { productId: raw.lead_item.product_id, name: raw.lead_item.name, imageUrl: raw.lead_item.image_url },
    lastEventAt: raw.last_event_at,
  }
}

export function toOrder(raw: S['OrderDetailResponse']): Order {
  return {
    ...toOrderSummary(raw),
    items: raw.items.map((line) => ({
      orderItemId: line.order_item_id,
      productId: line.product_id,
      name: line.name,
      quantity: line.quantity,
      unitPriceCents: line.unit_price_cents,
      discountCents: line.discount_cents,
      lineTotalCents: line.line_total_cents,
    })),
    subtotalCents: raw.subtotal_cents,
    discountCents: raw.discount_cents,
    couponId: raw.coupon_id,
    paidAt: raw.paid_at,
    closedAt: raw.closed_at,
    closeReason: raw.close_reason,
  }
}

export function toFulfillmentEvent(raw: S['FulfillmentEvent']): FulfillmentEvent {
  return {
    id: raw.id,
    eventType: raw.event_type,
    occurredAt: raw.occurred_at,
    sourceTimezone: raw.source_timezone,
  }
}
