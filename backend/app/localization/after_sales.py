"""售后工具的固定展示文案，确定性翻译，不处理顾客原文。"""

from app.localization.locales import SupportedLocale

_EN = {
    '售后资格由后端订单事实判定；请如实解释结果，不承诺例外': (
        'Eligibility is determined from order records; explain the result without '
        'promising exceptions.'
    ),
    '请向顾客说明当前规则允许的售后类型': (
        'Explain which after-sales options the current policy allows.'
    ),
    '只能选择本订单的商品行': (
        'Only items from this order can be selected.'
    ),
    '请重新选择本订单中的商品': (
        'Select items from this order again.'
    ),
    '平台演示售后规则：已退金额不可再次申请': (
        'Demo after-sales policy: refunded amounts cannot be claimed again.'
    ),
    '请核对订单行或联系客服': (
        'Check the order items or contact support.'
    ),
    '请在售后页面核对并确认，聊天中的确认不生效': (
        'Review and confirm on the after-sales page; confirmation in chat does not '
        'take effect.'
    ),
    '已准备售后预览；顾客须在页面上核对摘要和金额后亲自确认': (
        'Preview prepared; the customer must review the summary and amount and '
        'confirm on the page.'
    ),
    '平台演示售后规则：仅本版已支付订单可申请': (
        'Demo after-sales policy: only paid orders from this version are eligible.'
    ),
    '平台演示售后规则：已全额退款不可重复申请': (
        'Demo after-sales policy: fully refunded orders cannot be claimed again.'
    ),
    '平台演示售后规则：同一订单不可重复发起进行中的售后': (
        'Demo after-sales policy: an order cannot have multiple active after-sales '
        'requests.'
    ),
    '平台演示售后规则：未签收不受理退货，允许仅退款或工单': (
        'Demo after-sales policy: before delivery, only refund-only requests or '
        'support tickets are allowed.'
    ),
    '平台演示售后规则：签收后七天内申请': (
        'Demo after-sales policy: apply within seven days of delivery.'
    ),
    '本店有 {count} 条售后事项，请按状态和规则处理': (
        'This shop has {count} after-sales requests; handle them according to their '
        'status and policy.'
    ),
    '售后详情来自本店业务记录；顾客标识已脱敏': (
        "After-sales details come from this shop's records; customer identifiers are "
        'anonymized.'
    ),
    '售后决定已起草，须在审批界面批准后才会生效；退款金额由批准时后端计算。': (
        'Decision drafted; it takes effect only after approval on the approval page. '
        'The backend calculates the refund amount at approval.'
    ),
}


def after_sale_text(value: str, locale: SupportedLocale) -> str:
    return _EN[value] if locale is SupportedLocale.EN_US else value
