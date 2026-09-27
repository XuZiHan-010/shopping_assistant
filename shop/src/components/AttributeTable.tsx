import type { ProductAttribute, ProductLocale } from '@/types/shop'
import { TranslationNote } from './TranslationNote'

/**
 * 缺失属性显示「商家未提供」，不留空、不隐藏该行——顾客据此能看见「Agent 为什么说不知道」。
 * `DEMO` 来源的值明确标注，不冒充商家原文。
 */
export function AttributeTable({ attributes, locale = 'zh-CN' }: { attributes: ProductAttribute[]; locale?: ProductLocale }) {
  return (
    <table className="attrs">
      <tbody>
        {attributes.map((attribute) => {
          const value = attribute.value?.trim()
          return (
            <tr key={attribute.name}>
              <th scope="row">{attribute.name}<TranslationNote status={attribute.nameTranslationStatus} locale={locale} /></th>
              <td>
                {value ? value : <span className="muted">{locale === 'en-US' ? 'Not provided by merchant' : '商家未提供'}</span>}
                {value ? <TranslationNote status={attribute.valueTranslationStatus} locale={locale} /> : null}
                {value && attribute.source === 'DEMO' ? (
                  <span className="pill pill-warn" style={{ marginLeft: 8 }}>
                    {locale === 'en-US' ? 'Demo data' : '演示数据'}
                  </span>
                ) : null}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
