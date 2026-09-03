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
    empty: 'No conversation history yet. Once you ask a question, it will show up here for you to revisit.',
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
      detail:
        'Please try again later; contact support if it keeps happening.',
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
