import type { AppErrorCode } from '@/api/errors'

/**
 * 中文消息目录——类型事实源。`en-US.ts` 必须满足与本文件完全相同的 key
 * 形状（见该文件的 `satisfies MessageSchema`），`keys.ts` 从本文件派生
 * `MessageSchema` 类型。新增文案先加在这里，再补齐英文版本。
 *
 * `errorCopy` 子树额外用 `satisfies Record<AppErrorCode, ...>` 约束——
 * 后端在 `AppErrorCode` 新增错误码时，这里会在 typecheck 阶段直接报错，
 * 不会有新码悄悄漏掉文案（这条防线原来在 `utils/errorCopy.ts` 里，随文案
 * 一起搬过来）。`surface`/`action` 是行为分支用的协议枚举，不是给用户看的
 * 文案，因此不进这里，仍留在 `errorCopy.ts`。
 */
export const zhCN = {
  appMeta: {
    title: 'Borough 商家 AI 助手',
  },
  languageSwitcher: {
    switchToChinese: '切换到中文',
    switchToEnglish: '切换到英文',
    chinese: '中文',
    english: '英文',
  },
  appError: {
    close: '关闭',
  },
  conversationDrawer: {
    dialogLabel: '历史会话',
    title: '历史会话',
    closeAria: '关闭历史会话',
    deleteFailed: '删除失败，请稍后重试。',
    empty: '暂无历史会话。提问之后，这里会列出可以回看的会话。',
    confirmDeleteAria: '确认删除会话 {title}',
    confirmDelete: '确认删除',
    cancelDeleteAria: '取消删除',
    cancelDelete: '取消',
    deleteAria: '删除会话 {title}',
  },
  merchantSwitcher: {
    triggerAria: '切换当前演示商家',
    listAria: '演示商家',
  },
  assistantView: {
    skipLink: '跳到对话主内容',
    navAria: '打开对话目录',
    tagline: '经营数据、分析与行动建议',
    merchantLoading: '加载中',
    knowledgeLinkLabel: '知识库',
    knowledgeLinkAria: '知识库维护',
    opsLinkLabel: '看板',
    opsLinkAria: 'Chat BI 运营看板',
    newChatLabel: '新会话',
    insightsAside: '指标与洞察',
    actionsAside: '行动建议',
    dailyReportLoadFailed: '每日经营日报加载失败，请稍后重试。',
    dailyReportAdoptFailed: '采纳日报建议失败，请稍后重试。',
    conversationsLoadFailed: '历史会话加载失败，请稍后重试。',
  },
  chatComposer: {
    attachmentAria: '选择附件',
    inputAria: '输入问题',
    inputPlaceholder: '输入经营问题…',
    sendBusyAria: '上一轮回答仍在进行中',
    sendReadyAria: '发送问题',
    hintSubmit: 'Enter 发送 · Shift + Enter 换行',
    hintAttachments: '支持图片、PDF、Excel、CSV',
  },
  chatMessage: {
    preparing: '正在准备',
    cancelAria: '停止本次回答',
    cancelLabel: '停止',
    retryAfterCancelAria: '重新回答本轮问题',
    retryAfterCancelLabel: '重新回答',
    retryAria: '重试本轮问题',
    retryLabel: '重试',
    qualityGroupAria: '质量校验轨迹',
    qualityAttempts: '经过 {attempts} 次校验',
    qualityNotesSummary: '查看校验记录',
    qualitySourcesAria: '分析来源',
    degradedBadge: '演示数据',
    degradedFallbackReason: '本次回答未接入真实数据源，仅供演示参考。',
    degradedSourcesPrefix: '分析来源：',
    sourcesSeparator: '、',
    thinkingHeading: '执行完成',
    thinkingAria: '执行步骤',
    selectRoundAriaPrefix: '查看本轮分析：',
    historyDetailNotice:
      '历史明细仅保留{columns}列、{rows}行的元数据；重新提问可查看最新的数据表格与下载链接。',
    feedbackGroupAria: '回答反馈',
    feedbackPending: '保存中',
    feedbackPersisted: '已记录',
    adoptAria: '采纳本轮回答',
    adoptLabelDefault: '采纳',
    adoptLabelDone: '已采纳',
    likeAria: '给本轮回答点赞',
    likeLabel: '点赞',
    dislikeAria: '给本轮回答点踩',
    dislikeLabel: '点踩',
    quality: {
      passed: '前后比对通过',
      degraded: '校验未通过，已使用稳定兜底',
      failed: '前后比对未通过',
      notRun: '未执行校验',
    },
    source: {
      database: '经营数据',
      knowledge: '知识库',
      attachment: '附件',
      memory: '商家记忆',
      fallback: '兜底回答',
      none: '无外部来源',
    },
  },
  conversationNav: {
    navAria: '本次会话的轮次目录',
  },
  conversationColumn: {
    mainAria: '商家助手对话',
    welcomeTitle: '您好，我是您的经营助手',
    welcomeBody: '可以查询经营指标、查看业务明细，也可以结合数据给出分析与建议。',
    quickEyebrow: '快速体验',
    quickTitle: '点一个问题，看看助手能做什么',
    retryBusyNotice: '上一轮回答仍在处理中，请稍候再试。',
    defaultQuestion: '本轮提问',
  },
  dailyReportCard: {
    sectionAria: '每日经营日报',
    title: '每日经营日报',
    adoptDefault: '采纳本期建议',
    adoptDone: '已采纳本期建议',
  },
  detailTable: {
    sectionAria: '经营明细',
    caption: '经营明细',
    truncatedNotice: '共 {total} 行，已展示前 {shown} 行，完整数据请下载 CSV。',
    fullNotice: '共 {total} 行。',
    downloadLink: '下载明细 CSV（链接 {minutes} 分钟后过期）',
    expiredNotice: '下载链接已过期，重新提问可生成新的导出。',
  },
  metricChartPanel: {
    sectionAria: '指标图表',
    title: '指标图表',
    typeSwitcherAria: '图表类型',
    defaultChartTitle: '经营数据图表',
    viewTable: '查看数据表',
    emptyTitle: '暂无图表',
    emptyBody: '发起可视化类问题后，这里会显示图表。',
  },
  metricDefinitionPanel: {
    sectionAria: '指标口径',
    title: '指标口径',
    unverifiedFallback: '该指标口径尚未核验，请谨慎参考。',
    fieldDefinition: '业务口径',
    fieldSql: 'SQL 口径',
    fieldUnit: '单位',
    fieldSource: '来源',
    fieldSourceTable: '来源库表',
    fieldDimensions: '可用维度',
    dimensionsSeparator: '、',
    fieldReport: '关联报表',
    openReportLink: '打开关联报表',
    fieldOwner: '负责人',
    fieldStatus: '状态',
    queryPlanLabel: '查询计划摘要',
    emptyTitle: '暂无指标口径',
    emptyBody: '发起指标类问题后，这里会显示对应的指标定义、来源与负责人。',
    source: {
      metricCatalog: '正式指标目录',
      fieldComment: '受控字段注释',
      aiGenerated: '模型候选口径',
    },
    status: {
      active: '已核验',
      deprecated: '已弃用',
      unverified: '待核验',
    },
  },
  recommendationPanel: {
    emptyTitle: '暂无行动建议',
    emptyBody: '基于经营数据的建议和后续问题会显示在这里。',
    sectionAria: '行动建议',
    title: '行动建议',
    evidencePrefix: '依据：',
    actionPrefix: '建议：',
    noRecommendations: '本轮回答暂无可执行的行动建议。',
    suggestionsTitle: '猜你想问',
    rotate: '换一换',
    noSuggestions: '暂无推荐追问问题。',
  },
  errorCopy: {
    // —— 后端 ErrorCode（28 项） ——
    AUTH_REQUIRED: {
      title: '登录状态已失效',
      detail: '请重新选择商家登录后再试。',
    },
    MERCHANT_SCOPE_VIOLATION: {
      title: '无权访问该商家的数据',
      detail: '当前登录身份没有权限查看这份数据，请确认选择的商家是否正确。',
    },
    NOT_FOUND: {
      title: '未找到对应内容',
      detail: '你要查看的内容可能已被删除，或者链接有误。',
    },
    METHOD_NOT_ALLOWED: {
      title: '请求方式不受支持',
      detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    },
    INVALID_REQUEST: {
      title: '请求内容有误',
      detail: '请检查输入内容后重新提交。',
    },
    IDEMPOTENCY_KEY_REUSED: {
      title: '请求被判定为重复提交',
      detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    },
    REQUEST_IN_PROGRESS: {
      title: '上一条请求仍在处理',
      detail: '请等待当前回答完成后，再发送新的问题。',
    },
    /**
     * `POST /api/admin/reports/daily/recompute` 专属，该端点没有前端消费者
     * （`docs/specs/2026-08-24-daily-report-recompute-contract.md`）。这里只是
     * 为了让 `errorCopy` 保持穷尽，不会被任何 UI 路径触发。
     */
    DAILY_REPORT_FEEDBACK_CONFLICT: {
      title: '该日报已有反馈，无法重算',
      detail: '这是应用自身的问题，已自动记录，请联系管理员处理。',
    },
    DATA_SOURCE_UNAVAILABLE: {
      title: '经营数据暂时无法访问',
      detail: '数据查询服务暂不可用，请稍后重试。',
    },
    EXPORT_LINK_EXPIRED: {
      title: '导出链接已过期',
      detail: '请重新提问，系统会为你生成新的导出链接。',
    },
    RATE_LIMITED: {
      title: '请求过于频繁',
      detail: '请稍等片刻后再试。',
    },
    LLM_BUDGET_EXCEEDED: {
      title: '今日智能问答额度已用完',
      detail: '为控制成本，AI 问答的当日额度已达上限，请明天再来，或联系客服提升额度。',
    },
    FORBIDDEN: {
      title: '没有权限执行该操作',
      detail: '当前账号没有权限执行这个操作，如需继续请联系管理员。',
    },
    HTTP_ERROR: {
      title: '请求失败',
      detail: '服务暂时出现问题，请稍后重试；如果持续出现，请联系支持。',
    },
    INTERNAL_ERROR: {
      title: '服务器出现内部错误',
      detail: '我们已记录这个问题，请稍后重试；如果持续出现，请联系支持。',
    },
    INVALID_WIKI_PATH: {
      title: '知识库路径不合法',
      detail: '请检查目录和文件名后重试。',
    },
    WIKI_READ_ONLY: {
      title: '该知识库内容只读',
      detail: '商家记忆由系统自动沉淀，不能在后台直接修改。',
    },
    INVALID_FILE_TYPE: {
      title: '仅支持 Markdown 文档',
      detail: '请使用 .md 后缀的知识库文档。',
    },
    INVALID_WIKI_PARENT: {
      title: '目标目录不存在',
      detail: '请先创建对应业务域，再添加文档。',
    },
    WIKI_NODE_EXISTS: {
      title: '同名文档已存在',
      detail: '请更换文档名称后重试。',
    },
    WIKI_NODE_NOT_FOUND: {
      title: '未找到知识库文档',
      detail: '该文档可能已被删除或路径有误。',
    },
    WIKI_DIRECTORY_NOT_EMPTY: {
      title: '业务域仍包含文档',
      detail: '请确认后使用递归删除。',
    },
    WIKI_VERSION_REQUIRED: {
      title: '缺少文档版本',
      detail: '请重新加载文档后再保存。',
    },
    WIKI_VERSION_CONFLICT: {
      title: '文档已被其他维护者修改',
      detail: '请重新加载最新内容，并保留你当前的修改后再处理。',
    },
    WIKI_DOCUMENT_TOO_LARGE: {
      title: '文档内容过大',
      detail: '请缩短内容后再保存。',
    },
    INVALID_WIKI_ENCODING: {
      title: '文档编码不支持',
      detail: '请使用 UTF-8 编码的文本。',
    },
    INVALID_WIKI_CONTENT: {
      title: '文档内容不合法',
      detail: '请移除不支持的控制字符后重试。',
    },
    WIKI_IO_ERROR: {
      title: '知识库暂时无法写入',
      detail: '请稍后重试；如果持续出现，请联系支持。',
    },

    // —— 前端本地错误码（5 项） ——
    CONFIG: {
      title: '应用配置有误',
      detail: '应用缺少必要的配置项，无法连接后端服务，请联系技术支持。',
    },
    NETWORK: {
      title: '网络连接失败',
      detail: '请检查网络连接后重试。',
    },
    CANCELLED: {
      title: '请求已取消',
      detail: '本次请求已被取消，不会返回结果。',
    },
    STREAM_INTERRUPTED: {
      title: '回答流意外中断',
      detail: '连接在回答完成前中断，请重试。',
    },
    CONTRACT: {
      title: '返回内容不符合预期',
      detail: '这是应用自身的问题，已自动记录，请刷新页面后重试。',
    },
  } satisfies Record<AppErrorCode, { title: string; detail: string }>,
}
