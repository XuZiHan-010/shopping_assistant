import type { MessageSchema } from '../keys'

/**
 * 英文消息目录。必须满足 `zh-CN.ts` 派生出的 `MessageSchema`——多一个 key、
 * 少一个 key 都会在这里编译失败，不需要额外的漂移检查脚本。
 */
export const enUS = {
  appMeta: {
    title: 'Borough Merchant AI Assistant',
  },
  languageSwitcher: {
    switchToChinese: 'Switch to Chinese',
    switchToEnglish: 'Switch to English',
    chinese: 'Chinese',
    english: 'English',
  },
  appError: {
    close: 'Close',
  },
  conversationDrawer: {
    dialogLabel: 'Conversation history',
    title: 'Conversation history',
    closeAria: 'Close conversation history',
    deleteFailed: 'Delete failed. Please try again later.',
    empty:
      'No conversation history yet. Once you ask a question, it will show up here for you to revisit.',
    confirmDeleteAria: 'Confirm deleting conversation {title}',
    confirmDelete: 'Confirm delete',
    cancelDeleteAria: 'Cancel delete',
    cancelDelete: 'Cancel',
    deleteAria: 'Delete conversation {title}',
  },
  merchantSwitcher: {
    triggerAria: 'Switch current demo merchant',
    listAria: 'Demo merchants',
  },
  assistantView: {
    skipLink: 'Skip to conversation content',
    navAria: 'Open conversation history',
    tagline: 'Business data, analysis, and action recommendations',
    merchantLoading: 'Loading',
    knowledgeLinkLabel: 'Knowledge base',
    knowledgeLinkAria: 'Knowledge base maintenance',
    opsLinkLabel: 'Dashboard',
    opsLinkAria: 'Chat BI operations dashboard',
    newChatLabel: 'New chat',
    insightsAside: 'Metrics and insights',
    actionsAside: 'Action recommendations',
    dailyReportLoadFailed: 'Failed to load the daily report. Please try again later.',
    dailyReportAdoptFailed: 'Failed to adopt the daily report suggestions. Please try again later.',
    conversationsLoadFailed: 'Failed to load conversation history. Please try again later.',
  },
  chatComposer: {
    attachmentAria: 'Choose attachment',
    inputAria: 'Ask a question',
    inputPlaceholder: 'Ask a business question…',
    sendBusyAria: 'The previous answer is still in progress',
    sendReadyAria: 'Send question',
    hintSubmit: 'Enter to send · Shift + Enter for a new line',
    hintAttachments: 'Supports images, PDF, Excel, and CSV',
  },
  chatMessage: {
    preparing: 'Preparing',
    cancelAria: 'Stop this answer',
    cancelLabel: 'Stop',
    retryAfterCancelAria: 'Answer this question again',
    retryAfterCancelLabel: 'Answer again',
    retryAria: 'Retry this question',
    retryLabel: 'Retry',
    qualityGroupAria: 'Quality review trace',
    qualityAttempts: 'Reviewed {attempts} times',
    qualityNotesSummary: 'View review notes',
    qualitySourcesAria: 'Analysis sources',
    degradedBadge: 'Demo data',
    degradedFallbackReason:
      'This answer is not connected to a real data source and is for demo purposes only.',
    degradedSourcesPrefix: 'Analysis sources: ',
    sourcesSeparator: ', ',
    thinkingHeading: 'Completed',
    thinkingAria: 'Execution steps',
    selectRoundAriaPrefix: 'View this analysis: ',
    historyDetailNotice:
      'Only {columns} columns and {rows} rows of metadata are kept for history. Ask again to see the latest data table and download link.',
    feedbackGroupAria: 'Answer feedback',
    feedbackPending: 'Saving',
    feedbackPersisted: 'Saved',
    adoptAria: 'Adopt this answer',
    adoptLabelDefault: 'Adopt',
    adoptLabelDone: 'Adopted',
    likeAria: 'Like this answer',
    likeLabel: 'Like',
    dislikeAria: 'Dislike this answer',
    dislikeLabel: 'Dislike',
    quality: {
      passed: 'Before/after comparison passed',
      degraded: 'Validation failed; a stable fallback was used',
      failed: 'Before/after comparison failed',
      notRun: 'Validation not run',
    },
    source: {
      database: 'Business data',
      knowledge: 'Knowledge base',
      attachment: 'Attachment',
      memory: 'Merchant memory',
      fallback: 'Fallback answer',
      none: 'No external source',
    },
  },
  conversationNav: {
    navAria: 'Round index for this conversation',
  },
  conversationColumn: {
    mainAria: 'Merchant assistant conversation',
    welcomeTitle: "Hi, I'm your business assistant",
    welcomeBody:
      'I can look up business metrics, show business details, and combine data into analysis and recommendations.',
    quickEyebrow: 'Quick start',
    quickTitle: 'Tap a question to see what the assistant can do',
    retryBusyNotice: 'The previous answer is still being processed. Please try again shortly.',
    defaultQuestion: 'This round’s question',
  },
  dailyReportCard: {
    sectionAria: 'Daily business report',
    title: 'Daily business report',
    adoptDefault: 'Adopt this report',
    adoptDone: 'Report adopted',
  },
  detailTable: {
    sectionAria: 'Business details',
    caption: 'Business details',
    truncatedNotice:
      '{total} rows total, showing the first {shown}. Download the CSV for the full data.',
    fullNotice: '{total} rows total.',
    downloadLink: 'Download details CSV (link expires in {minutes} minutes)',
    expiredNotice: 'The download link has expired. Ask again to generate a new export.',
  },
  metricChartPanel: {
    sectionAria: 'Metric chart',
    title: 'Metric chart',
    typeSwitcherAria: 'Chart type',
    defaultChartTitle: 'Business data chart',
    viewTable: 'View data table',
    emptyTitle: 'No chart yet',
    emptyBody: 'Ask a visualization-friendly question and a chart will show up here.',
  },
  metricDefinitionPanel: {
    sectionAria: 'Metric definition',
    title: 'Metric definition',
    unverifiedFallback:
      'This metric definition has not been verified yet. Please use it with caution.',
    fieldDefinition: 'Business definition',
    fieldSql: 'SQL definition',
    fieldUnit: 'Unit',
    fieldSource: 'Source',
    fieldSourceTable: 'Source table',
    fieldDimensions: 'Available dimensions',
    dimensionsSeparator: ', ',
    fieldReport: 'Related report',
    openReportLink: 'Open related report',
    fieldOwner: 'Owner',
    fieldStatus: 'Status',
    queryPlanLabel: 'Query plan summary',
    emptyTitle: 'No metric definition yet',
    emptyBody:
      'Ask a metric-related question and the matching definition, source, and owner will show up here.',
    source: {
      metricCatalog: 'Official metric catalog',
      fieldComment: 'Governed field comment',
      aiGenerated: 'Model-proposed definition',
    },
    status: {
      active: 'Verified',
      deprecated: 'Deprecated',
      unverified: 'Pending verification',
    },
  },
  recommendationPanel: {
    emptyTitle: 'No recommendations yet',
    emptyBody: 'Recommendations and follow-up questions based on business data will show up here.',
    sectionAria: 'Action recommendations',
    title: 'Action recommendations',
    evidencePrefix: 'Evidence: ',
    actionPrefix: 'Recommendation: ',
    noRecommendations: 'This answer has no actionable recommendations.',
    suggestionsTitle: 'You might also ask',
    rotate: 'Shuffle',
    noSuggestions: 'No suggested follow-up questions yet.',
  },
  knowledgeBaseView: {
    title: 'Knowledge base administration',
    signOut: 'Sign out',
    newDocument: 'New document',
    renameDomain: 'Rename business domain',
    deleteNode: 'Delete',
    loadingTree: 'Loading knowledge directory…',
    selectDocumentPrompt: 'Select a document to maintain.',
    tokenVerificationFailed: 'Admin token verification failed.',
    actionFailed: 'Action failed. Please try again.',
    deleteFailed: 'Delete failed. Please try again.',
    createDocumentTitle: 'New document',
    createDocumentLabel: 'Document name',
    createDocumentPlaceholder: 'e.g. order-fulfillment-definition.md',
    createDomainTitle: 'New business domain',
    createDomainLabel: 'Business domain name',
    createDomainPlaceholder: 'e.g. Customer Service',
    renameDomainTitle: 'Rename business domain',
    renameDomainLabel: 'Business domain name',
  },
  adminTokenDialog: {
    eyebrow: 'BOROUGH · KNOWLEDGE OPS',
    title: 'Knowledge base administration',
    instructions: 'Enter the admin token to continue.',
    tokenLabel: 'Admin token',
    viewerToggleLabel: 'Browse with the read-only token',
    submit: 'Enter administration',
  },
  confirmDeleteDialog: {
    title: 'Delete knowledge node',
    domainWarning:
      'This business domain and all of its documents will be cascade-deleted. This cannot be undone.',
    documentWarning: 'This document will be deleted. This cannot be undone.',
    cancel: 'Cancel',
    confirmPending: 'Deleting…',
    confirm: 'Confirm delete',
  },
  promptDialog: {
    cancel: 'Cancel',
    submitDefault: 'Confirm',
    pending: 'Processing…',
  },
  knowledgeTree: {
    navAria: 'Knowledge base directory',
    title: 'Knowledge directory',
    createDomainLabel: '+ Domain',
    createDomainAria: 'New business domain',
    readOnlyBadge: 'Read-only',
  },
  documentEditor: {
    memoryReadOnlyBadge: 'Memory (read-only)',
    contentAria: '{path} content',
    save: 'Save changes',
    conflictMessage:
      'This document was modified by another maintainer. Please reload and merge your changes.',
  },
  errorCopy: {
    // —— Backend ErrorCode (28 entries) ——
    AUTH_REQUIRED: {
      title: 'Your session has expired',
      detail: 'Please choose a merchant to sign in again and retry.',
    },
    MERCHANT_SCOPE_VIOLATION: {
      title: "You don't have access to this merchant's data",
      detail:
        'Your current sign-in has no permission to view this data. Please confirm the selected merchant is correct.',
    },
    NOT_FOUND: {
      title: 'Content not found',
      detail: 'The content you are looking for may have been removed, or the link is incorrect.',
    },
    METHOD_NOT_ALLOWED: {
      title: 'Request method not supported',
      detail:
        'This is an issue with the app itself and has been logged automatically. Please refresh the page and try again.',
    },
    INVALID_REQUEST: {
      title: 'There is a problem with the request',
      detail: 'Please check your input and submit again.',
    },
    IDEMPOTENCY_KEY_REUSED: {
      title: 'The request was detected as a duplicate submission',
      detail:
        'This is an issue with the app itself and has been logged automatically. Please refresh the page and try again.',
    },
    REQUEST_IN_PROGRESS: {
      title: 'The previous request is still processing',
      detail: 'Please wait for the current answer to finish before sending a new question.',
    },
    /**
     * Dedicated to `POST /api/admin/reports/daily/recompute`, which has no
     * frontend caller (`docs/specs/2026-08-24-daily-report-recompute-contract.md`).
     * This entry only keeps `errorCopy` exhaustive and is never triggered by
     * any UI path.
     */
    DAILY_REPORT_FEEDBACK_CONFLICT: {
      title: 'This daily report already has feedback and cannot be recomputed',
      detail:
        'This is an issue with the app itself and has been logged automatically. Please contact an administrator.',
    },
    DATA_SOURCE_UNAVAILABLE: {
      title: 'Business data is temporarily unavailable',
      detail: 'The data query service is temporarily unavailable. Please try again later.',
    },
    EXPORT_LINK_EXPIRED: {
      title: 'The export link has expired',
      detail: 'Please ask again and the system will generate a new export link for you.',
    },
    RATE_LIMITED: {
      title: 'Too many requests',
      detail: 'Please wait a moment and try again.',
    },
    LLM_BUDGET_EXCEEDED: {
      title: "Today's AI quota has been used up",
      detail:
        'To control cost, the daily quota for AI-powered answers has been reached. Please come back tomorrow, or contact support to raise your quota.',
    },
    FORBIDDEN: {
      title: 'You do not have permission to perform this action',
      detail:
        'Your current account does not have permission to perform this action. Please contact an administrator if you need to continue.',
    },
    HTTP_ERROR: {
      title: 'Request failed',
      detail:
        'The service is temporarily experiencing issues. Please try again later; contact support if it keeps happening.',
    },
    INTERNAL_ERROR: {
      title: 'The server encountered an internal error',
      detail:
        "We've logged this issue. Please try again later; contact support if it keeps happening.",
    },
    INVALID_WIKI_PATH: {
      title: 'The knowledge base path is invalid',
      detail: 'Please check the directory and file name and try again.',
    },
    WIKI_READ_ONLY: {
      title: 'This knowledge base content is read-only',
      detail:
        'Merchant memories are captured automatically by the system and cannot be edited directly in the admin console.',
    },
    INVALID_FILE_TYPE: {
      title: 'Only Markdown documents are supported',
      detail: 'Please use a knowledge base document with a .md extension.',
    },
    INVALID_WIKI_PARENT: {
      title: 'The target directory does not exist',
      detail: 'Please create the corresponding business domain first, then add the document.',
    },
    WIKI_NODE_EXISTS: {
      title: 'A document with this name already exists',
      detail: 'Please rename the document and try again.',
    },
    WIKI_NODE_NOT_FOUND: {
      title: 'Knowledge base document not found',
      detail: 'This document may have been deleted, or the path is incorrect.',
    },
    WIKI_DIRECTORY_NOT_EMPTY: {
      title: 'The business domain still contains documents',
      detail: 'Please confirm and use recursive delete.',
    },
    WIKI_VERSION_REQUIRED: {
      title: 'Document version is missing',
      detail: 'Please reload the document and save again.',
    },
    WIKI_VERSION_CONFLICT: {
      title: 'This document was modified by another maintainer',
      detail: 'Please reload the latest content, keep your current changes, and try again.',
    },
    WIKI_DOCUMENT_TOO_LARGE: {
      title: 'The document content is too large',
      detail: 'Please shorten the content and save again.',
    },
    INVALID_WIKI_ENCODING: {
      title: 'This document encoding is not supported',
      detail: 'Please use UTF-8 encoded text.',
    },
    INVALID_WIKI_CONTENT: {
      title: 'The document content is invalid',
      detail: 'Please remove unsupported control characters and try again.',
    },
    WIKI_IO_ERROR: {
      title: 'The knowledge base is temporarily unable to write',
      detail: 'Please try again later; contact support if it keeps happening.',
    },

    // —— Local frontend error codes (5 entries) ——
    CONFIG: {
      title: 'The app is misconfigured',
      detail:
        'The app is missing a required configuration value and cannot reach the backend service. Please contact technical support.',
    },
    NETWORK: {
      title: 'Network connection failed',
      detail: 'Please check your network connection and try again.',
    },
    CANCELLED: {
      title: 'Request cancelled',
      detail: 'This request was cancelled and will not return a result.',
    },
    STREAM_INTERRUPTED: {
      title: 'The answer stream was interrupted unexpectedly',
      detail: 'The connection was interrupted before the answer finished. Please try again.',
    },
    CONTRACT: {
      title: 'The response did not match the expected contract',
      detail:
        'This is an issue with the app itself and has been logged automatically. Please refresh the page and try again.',
    },
  },
} satisfies MessageSchema
