# OpenAPI

> 本文件由 `scripts/export_openapi.py` 生成，请勿手改；改契约请改 Pydantic Schema 后重新导出。

```json
{
  "openapi": "3.1.0",
  "info": {
    "title": "Borough 商家 AI 助手 API",
    "version": "0.1.0"
  },
  "paths": {
    "/api/health": {
      "get": {
        "tags": [
          "health"
        ],
        "summary": "Health",
        "description": "返回进程健康状态，不访问数据库或 LLM。",
        "operationId": "health_api_health_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HealthResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/ready": {
      "get": {
        "tags": [
          "health"
        ],
        "summary": "Ready",
        "description": "执行轻量数据库 readiness 探针。",
        "operationId": "ready_api_ready_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ReadyResponse"
                }
              }
            }
          },
          "503": {
            "description": "依赖服务暂时不可用",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/demo/merchants": {
      "get": {
        "tags": [
          "demo"
        ],
        "summary": "List Demo Merchants",
        "description": "返回受控演示商家及其权限受限 Token。",
        "operationId": "list_demo_merchants_api_demo_merchants_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/DemoMerchantListResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/chat": {
      "post": {
        "tags": [
          "chat"
        ],
        "summary": "Post Chat",
        "description": "默认返回 SSE；明确请求 JSON 时返回与 done 同构的响应。",
        "operationId": "post_chat_api_chat_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/ChatRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "默认返回 `text/event-stream`；请求头带 `Accept: application/json` 时返回普通 JSON。SSE 只发送 `step`、`done`、`error` 三种事件，流必须以 `done` 或 `error` 收尾。`step` 载荷是 `ThinkingStep`，`done` 载荷与 JSON 路径的 `ChatResponse` 逐字段相同，`error` 载荷是 `ErrorResponse`。",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ChatResponse"
                }
              },
              "text/event-stream": {
                "schema": {
                  "type": "string"
                },
                "example": "event: step\ndata: {\"label\":\"识别商家与业务意图\",\"node\":\"classify\"}\n\nevent: done\ndata: {\"id\":\"...\",\"session_id\":\"...\",\"answer\":\"...\"}\n\n"
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "409": {
            "description": "幂等键冲突或同一请求正在处理中",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "429": {
            "description": "请求过于频繁",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "503": {
            "description": "依赖服务暂时不可用",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        },
        "security": [
          {
            "HTTPBearer": []
          }
        ]
      }
    },
    "/api/conversations": {
      "get": {
        "tags": [
          "chat"
        ],
        "summary": "List Conversations",
        "operationId": "list_conversations_api_conversations_get",
        "security": [
          {
            "HTTPBearer": []
          }
        ],
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "maximum": 100,
              "minimum": 1,
              "default": 20,
              "title": "Limit"
            }
          },
          {
            "name": "offset",
            "in": "query",
            "required": false,
            "schema": {
              "type": "integer",
              "minimum": 0,
              "default": 0,
              "title": "Offset"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ConversationListResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/conversations/{conversation_id}": {
      "get": {
        "tags": [
          "chat"
        ],
        "summary": "Get Conversation",
        "operationId": "get_conversation_api_conversations__conversation_id__get",
        "security": [
          {
            "HTTPBearer": []
          }
        ],
        "parameters": [
          {
            "name": "conversation_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Conversation Id"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ConversationDetailResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      },
      "delete": {
        "tags": [
          "chat"
        ],
        "summary": "Delete Conversation",
        "operationId": "delete_conversation_api_conversations__conversation_id__delete",
        "security": [
          {
            "HTTPBearer": []
          }
        ],
        "parameters": [
          {
            "name": "conversation_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Conversation Id"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "Successful Response"
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/exports/{export_id}": {
      "get": {
        "tags": [
          "exports"
        ],
        "summary": "Download Export",
        "operationId": "download_export_api_exports__export_id__get",
        "parameters": [
          {
            "name": "export_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Export Id"
            }
          },
          {
            "name": "merchant_id",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Merchant Id"
            }
          },
          {
            "name": "expires_at",
            "in": "query",
            "required": true,
            "schema": {
              "type": "integer",
              "minimum": 0,
              "title": "Expires At"
            }
          },
          {
            "name": "signature",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "minLength": 32,
              "maxLength": 128,
              "title": "Signature"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {}
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "410": {
            "description": "导出链接已过期",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/answers/{answer_id}/feedback": {
      "post": {
        "tags": [
          "feedback"
        ],
        "summary": "Save Feedback",
        "operationId": "save_feedback_api_answers__answer_id__feedback_post",
        "security": [
          {
            "HTTPBearer": []
          }
        ],
        "parameters": [
          {
            "name": "answer_id",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "format": "uuid",
              "title": "Answer Id"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/FeedbackRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/FeedbackResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/metrics/{code}": {
      "get": {
        "tags": [
          "metrics"
        ],
        "summary": "Get Metric Definition",
        "description": "返回正式指标口径。指标目录对所有商家一致，因此不按商家过滤。",
        "operationId": "get_metric_definition_api_metrics__code__get",
        "security": [
          {
            "HTTPBearer": []
          }
        ],
        "parameters": [
          {
            "name": "code",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Code"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/MetricDefinitionResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/admin/ops/status": {
      "get": {
        "tags": [
          "admin"
        ],
        "summary": "Ops Status",
        "operationId": "ops_status_api_admin_ops_status_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/OpsStatusResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/admin/knowledge/tree": {
      "get": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Get Knowledge Tree",
        "operationId": "get_knowledge_tree_api_admin_knowledge_tree_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/KnowledgeTreeResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/admin/knowledge/documents/{document_path}": {
      "get": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Get Document",
        "operationId": "get_document_api_admin_knowledge_documents__document_path__get",
        "parameters": [
          {
            "name": "document_path",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Document Path"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/KnowledgeDocumentResponse"
                }
              }
            }
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      },
      "put": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Update Document",
        "operationId": "update_document_api_admin_knowledge_documents__document_path__put",
        "parameters": [
          {
            "name": "document_path",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Document Path"
            }
          },
          {
            "name": "if-match",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "If-Match"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/KnowledgeDocumentUpdateRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/KnowledgeDocumentResponse"
                }
              }
            }
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "412": {
            "description": "资源已被其他维护者更新",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "413": {
            "description": "请求内容超过允许大小",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "415": {
            "description": "请求内容编码不受支持",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "428": {
            "description": "请求缺少条件版本",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      },
      "delete": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Delete Document",
        "operationId": "delete_document_api_admin_knowledge_documents__document_path__delete",
        "parameters": [
          {
            "name": "document_path",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Document Path"
            }
          },
          {
            "name": "if-match",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "If-Match"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "Successful Response"
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "412": {
            "description": "资源已被其他维护者更新",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "428": {
            "description": "请求缺少条件版本",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/admin/knowledge/documents": {
      "post": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Create Document",
        "operationId": "create_document_api_admin_knowledge_documents_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/KnowledgeDocumentRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "201": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/KnowledgeDocumentResponse"
                }
              }
            }
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "409": {
            "description": "幂等键冲突或同一请求正在处理中",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "413": {
            "description": "请求内容超过允许大小",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "415": {
            "description": "请求内容编码不受支持",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/admin/knowledge/business-domains": {
      "post": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Create Business Domain",
        "operationId": "create_business_domain_api_admin_knowledge_business_domains_post",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/BusinessDomainRequest"
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/KnowledgeTreeNode"
                }
              }
            }
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "409": {
            "description": "幂等键冲突或同一请求正在处理中",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      },
      "put": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Rename Business Domain",
        "operationId": "rename_business_domain_api_admin_knowledge_business_domains_put",
        "parameters": [
          {
            "name": "name",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Name"
            }
          },
          {
            "name": "if-match",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "If-Match"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/BusinessDomainRenameRequest"
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/KnowledgeTreeNode"
                }
              }
            }
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "409": {
            "description": "幂等键冲突或同一请求正在处理中",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "412": {
            "description": "资源已被其他维护者更新",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "428": {
            "description": "请求缺少条件版本",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      },
      "delete": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Delete Business Domain",
        "operationId": "delete_business_domain_api_admin_knowledge_business_domains_delete",
        "parameters": [
          {
            "name": "name",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Name"
            }
          },
          {
            "name": "recursive",
            "in": "query",
            "required": false,
            "schema": {
              "type": "boolean",
              "default": false,
              "title": "Recursive"
            }
          },
          {
            "name": "if-match",
            "in": "header",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "If-Match"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "Successful Response"
          },
          "400": {
            "description": "请求内容不符合业务规则",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "409": {
            "description": "幂等键冲突或同一请求正在处理中",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "412": {
            "description": "资源已被其他维护者更新",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "428": {
            "description": "请求缺少条件版本",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    },
    "/api/admin/knowledge/memories/compress": {
      "post": {
        "tags": [
          "admin-knowledge"
        ],
        "summary": "Compress Memory",
        "description": "以管理员身份手动重压指定商家的分类记忆。",
        "operationId": "compress_memory_api_admin_knowledge_memories_compress_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/MemoryCompressRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/MemoryCompressResponse"
                }
              }
            }
          },
          "401": {
            "description": "缺少或提供了无效的商家凭证",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "403": {
            "description": "无权访问该资源或管理端点",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "404": {
            "description": "资源不存在",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "422": {
            "description": "请求参数不合法",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "AnalysisSource": {
        "type": "string",
        "enum": [
          "DATABASE",
          "KNOWLEDGE",
          "ATTACHMENT",
          "MEMORY",
          "FALLBACK",
          "NONE"
        ],
        "title": "AnalysisSource"
      },
      "AnswerMode": {
        "type": "string",
        "enum": [
          "METRIC",
          "DETAIL",
          "RULE",
          "IDENTITY",
          "CHAT",
          "INVALID",
          "ATTACHMENT"
        ],
        "title": "AnswerMode",
        "description": "回答模式。ATTACHMENT 为 P1 预留值，B2 不产生该模式。"
      },
      "BusinessDomainRenameRequest": {
        "properties": {
          "new_name": {
            "type": "string",
            "title": "New Name"
          }
        },
        "type": "object",
        "required": [
          "new_name"
        ],
        "title": "BusinessDomainRenameRequest"
      },
      "BusinessDomainRequest": {
        "properties": {
          "name": {
            "type": "string",
            "title": "Name"
          }
        },
        "type": "object",
        "required": [
          "name"
        ],
        "title": "BusinessDomainRequest"
      },
      "ChartType": {
        "type": "string",
        "enum": [
          "LINE",
          "BAR",
          "PIE"
        ],
        "title": "ChartType",
        "description": "后端允许的图表类型。\n\n约束在契约侧声明后由 OpenAPI 自动传给前端，Adapter 无须自行窄化自由字符串。"
      },
      "ChatRequest": {
        "properties": {
          "message": {
            "type": "string",
            "maxLength": 4000,
            "minLength": 1,
            "title": "Message"
          },
          "session_id": {
            "anyOf": [
              {
                "type": "string",
                "format": "uuid"
              },
              {
                "type": "null"
              }
            ],
            "title": "Session Id"
          },
          "attachment_ids": {
            "items": {
              "type": "string",
              "format": "uuid"
            },
            "type": "array",
            "maxItems": 0,
            "title": "Attachment Ids"
          },
          "client_request_id": {
            "type": "string",
            "maxLength": 128,
            "minLength": 1,
            "title": "Client Request Id"
          }
        },
        "type": "object",
        "required": [
          "message",
          "client_request_id"
        ],
        "title": "ChatRequest"
      },
      "ChatResponse": {
        "properties": {
          "id": {
            "type": "string",
            "format": "uuid",
            "title": "Id"
          },
          "session_id": {
            "type": "string",
            "format": "uuid",
            "title": "Session Id"
          },
          "answer": {
            "type": "string",
            "title": "Answer"
          },
          "answer_mode": {
            "$ref": "#/components/schemas/AnswerMode"
          },
          "category": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/QuestionCategory"
              },
              {
                "type": "null"
              }
            ]
          },
          "thinking_steps": {
            "items": {
              "$ref": "#/components/schemas/ThinkingStep"
            },
            "type": "array",
            "title": "Thinking Steps"
          },
          "quality_status": {
            "$ref": "#/components/schemas/QualityStatus"
          },
          "quality_attempts": {
            "type": "integer",
            "maximum": 2.0,
            "minimum": 0.0,
            "title": "Quality Attempts"
          },
          "quality_notes": {
            "items": {
              "type": "string"
            },
            "type": "array",
            "title": "Quality Notes"
          },
          "analysis_sources": {
            "items": {
              "$ref": "#/components/schemas/AnalysisSource"
            },
            "type": "array",
            "minItems": 1,
            "title": "Analysis Sources"
          },
          "degraded": {
            "type": "boolean",
            "title": "Degraded"
          },
          "degraded_reason": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Degraded Reason"
          },
          "suggestions": {
            "items": {
              "type": "string"
            },
            "type": "array",
            "title": "Suggestions"
          },
          "suggestion_alternates": {
            "items": {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            "type": "array",
            "title": "Suggestion Alternates"
          },
          "created_at": {
            "type": "string",
            "format": "date-time",
            "title": "Created At"
          },
          "query_plan": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/QueryPlanSummary"
              },
              {
                "type": "null"
              }
            ]
          },
          "metric_code": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Code"
          },
          "metric_display_name": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Display Name"
          },
          "metric_unit": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Unit"
          },
          "metric_definition": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Definition"
          },
          "metric_sql_definition": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Sql Definition"
          },
          "metric_dimensions": {
            "anyOf": [
              {
                "items": {
                  "type": "string"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Dimensions"
          },
          "metric_source_database": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Source Database"
          },
          "metric_source_table": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Source Table"
          },
          "metric_report_url": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Report Url"
          },
          "metric_source": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/MetricDefinitionSource"
              },
              {
                "type": "null"
              }
            ]
          },
          "metric_generated": {
            "anyOf": [
              {
                "type": "boolean"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Generated"
          },
          "metric_notice": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Notice"
          },
          "metric_owner": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Owner"
          },
          "metric_status": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/MetricStatus"
              },
              {
                "type": "null"
              }
            ]
          },
          "data_rows": {
            "anyOf": [
              {
                "items": {
                  "additionalProperties": true,
                  "type": "object"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "title": "Data Rows"
          },
          "total_rows": {
            "anyOf": [
              {
                "type": "integer",
                "minimum": 0.0
              },
              {
                "type": "null"
              }
            ],
            "title": "Total Rows"
          },
          "truncated": {
            "anyOf": [
              {
                "type": "boolean"
              },
              {
                "type": "null"
              }
            ],
            "title": "Truncated"
          },
          "export": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/ExportInfo"
              },
              {
                "type": "null"
              }
            ]
          },
          "visualization": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/Visualization"
              },
              {
                "type": "null"
              }
            ]
          },
          "recommendations": {
            "anyOf": [
              {
                "items": {
                  "$ref": "#/components/schemas/Recommendation"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "title": "Recommendations"
          }
        },
        "type": "object",
        "required": [
          "id",
          "session_id",
          "answer",
          "answer_mode",
          "category",
          "quality_status",
          "quality_attempts",
          "analysis_sources",
          "degraded",
          "degraded_reason"
        ],
        "title": "ChatResponse",
        "description": "§8.2 的扁平响应；按模式字段由模型级校验控制。"
      },
      "ConversationAnswerPayload": {
        "properties": {
          "answer_id": {
            "type": "string",
            "format": "uuid",
            "title": "Answer Id"
          },
          "answer_mode": {
            "$ref": "#/components/schemas/AnswerMode"
          },
          "thinking_steps": {
            "items": {
              "$ref": "#/components/schemas/ThinkingStep"
            },
            "type": "array",
            "title": "Thinking Steps"
          },
          "quality_status": {
            "$ref": "#/components/schemas/QualityStatus"
          },
          "quality_attempts": {
            "type": "integer",
            "maximum": 2.0,
            "minimum": 0.0,
            "title": "Quality Attempts"
          },
          "quality_notes": {
            "items": {
              "type": "string"
            },
            "type": "array",
            "title": "Quality Notes"
          },
          "degraded": {
            "type": "boolean",
            "title": "Degraded"
          },
          "degraded_reason": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Degraded Reason"
          },
          "is_adopted": {
            "type": "boolean",
            "title": "Is Adopted"
          },
          "reaction": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/FeedbackReaction"
              },
              {
                "type": "null"
              }
            ]
          },
          "columns": {
            "items": {
              "type": "string"
            },
            "type": "array",
            "title": "Columns"
          },
          "total_rows": {
            "anyOf": [
              {
                "type": "integer",
                "minimum": 0.0
              },
              {
                "type": "null"
              }
            ],
            "title": "Total Rows"
          },
          "truncated": {
            "anyOf": [
              {
                "type": "boolean"
              },
              {
                "type": "null"
              }
            ],
            "title": "Truncated"
          }
        },
        "type": "object",
        "required": [
          "answer_id",
          "answer_mode",
          "quality_status",
          "quality_attempts",
          "degraded",
          "degraded_reason",
          "is_adopted",
          "reaction"
        ],
        "title": "ConversationAnswerPayload",
        "description": "会话详情中的助手回答脱敏载荷，不携带明细行和导出 URL。"
      },
      "ConversationDetailResponse": {
        "properties": {
          "id": {
            "type": "string",
            "format": "uuid",
            "title": "Id"
          },
          "title": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Title"
          },
          "messages": {
            "items": {
              "$ref": "#/components/schemas/ConversationMessage"
            },
            "type": "array",
            "title": "Messages"
          },
          "created_at": {
            "type": "string",
            "format": "date-time",
            "title": "Created At"
          },
          "updated_at": {
            "type": "string",
            "format": "date-time",
            "title": "Updated At"
          }
        },
        "type": "object",
        "required": [
          "id",
          "title",
          "messages",
          "created_at",
          "updated_at"
        ],
        "title": "ConversationDetailResponse"
      },
      "ConversationListResponse": {
        "properties": {
          "items": {
            "items": {
              "$ref": "#/components/schemas/ConversationSummary"
            },
            "type": "array",
            "title": "Items"
          },
          "limit": {
            "type": "integer",
            "maximum": 100.0,
            "minimum": 1.0,
            "title": "Limit"
          },
          "offset": {
            "type": "integer",
            "minimum": 0.0,
            "title": "Offset"
          }
        },
        "type": "object",
        "required": [
          "items",
          "limit",
          "offset"
        ],
        "title": "ConversationListResponse"
      },
      "ConversationMessage": {
        "properties": {
          "id": {
            "type": "string",
            "format": "uuid",
            "title": "Id"
          },
          "role": {
            "type": "string",
            "title": "Role"
          },
          "content": {
            "type": "string",
            "title": "Content"
          },
          "created_at": {
            "type": "string",
            "format": "date-time",
            "title": "Created At"
          },
          "answer_payload": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/ConversationAnswerPayload"
              },
              {
                "type": "null"
              }
            ]
          }
        },
        "type": "object",
        "required": [
          "id",
          "role",
          "content",
          "created_at"
        ],
        "title": "ConversationMessage"
      },
      "ConversationSummary": {
        "properties": {
          "id": {
            "type": "string",
            "format": "uuid",
            "title": "Id"
          },
          "title": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Title"
          },
          "created_at": {
            "type": "string",
            "format": "date-time",
            "title": "Created At"
          },
          "updated_at": {
            "type": "string",
            "format": "date-time",
            "title": "Updated At"
          }
        },
        "type": "object",
        "required": [
          "id",
          "title",
          "created_at",
          "updated_at"
        ],
        "title": "ConversationSummary"
      },
      "DemoMerchant": {
        "properties": {
          "merchant_id": {
            "type": "string",
            "format": "uuid",
            "title": "Merchant Id"
          },
          "display_name": {
            "type": "string",
            "title": "Display Name"
          },
          "token": {
            "type": "string",
            "title": "Token"
          }
        },
        "type": "object",
        "required": [
          "merchant_id",
          "display_name",
          "token"
        ],
        "title": "DemoMerchant"
      },
      "DemoMerchantListResponse": {
        "properties": {
          "merchants": {
            "items": {
              "$ref": "#/components/schemas/DemoMerchant"
            },
            "type": "array",
            "title": "Merchants"
          }
        },
        "type": "object",
        "required": [
          "merchants"
        ],
        "title": "DemoMerchantListResponse"
      },
      "ErrorCode": {
        "type": "string",
        "enum": [
          "AUTH_REQUIRED",
          "MERCHANT_SCOPE_VIOLATION",
          "NOT_FOUND",
          "METHOD_NOT_ALLOWED",
          "INVALID_REQUEST",
          "IDEMPOTENCY_KEY_REUSED",
          "REQUEST_IN_PROGRESS",
          "DATA_SOURCE_UNAVAILABLE",
          "EXPORT_LINK_EXPIRED",
          "RATE_LIMITED",
          "LLM_BUDGET_EXCEEDED",
          "FORBIDDEN",
          "HTTP_ERROR",
          "INTERNAL_ERROR",
          "INVALID_WIKI_PATH",
          "WIKI_READ_ONLY",
          "INVALID_FILE_TYPE",
          "INVALID_WIKI_PARENT",
          "WIKI_NODE_EXISTS",
          "WIKI_NODE_NOT_FOUND",
          "WIKI_DIRECTORY_NOT_EMPTY",
          "WIKI_VERSION_REQUIRED",
          "WIKI_VERSION_CONFLICT",
          "WIKI_DOCUMENT_TOO_LARGE",
          "INVALID_WIKI_ENCODING",
          "INVALID_WIKI_CONTENT",
          "WIKI_IO_ERROR"
        ],
        "title": "ErrorCode",
        "description": "对外错误码。\n\n这是后端实际会发出的错误码的唯一出处——不要在别处直写字符串字面量。\n每个成员都必须同时登记在 `docs/backend-development-plan.md` §14，\n否则前端按码查表渲染时会漏网（见 `docs/frontend-development-plan.md` §10）。\n\n后续阶段（B3 起的意图、查询、限流、附件等）按需扩充。"
      },
      "ErrorResponse": {
        "properties": {
          "code": {
            "$ref": "#/components/schemas/ErrorCode"
          },
          "message": {
            "type": "string",
            "title": "Message"
          },
          "request_id": {
            "type": "string",
            "title": "Request Id"
          },
          "details": {
            "items": {
              "additionalProperties": true,
              "type": "object"
            },
            "type": "array",
            "title": "Details"
          },
          "retryable": {
            "type": "boolean",
            "title": "Retryable",
            "default": false
          }
        },
        "type": "object",
        "required": [
          "code",
          "message",
          "request_id"
        ],
        "title": "ErrorResponse",
        "description": "对外稳定错误契约。"
      },
      "ExportInfo": {
        "properties": {
          "id": {
            "type": "string",
            "format": "uuid",
            "title": "Id"
          },
          "url": {
            "type": "string",
            "title": "Url"
          },
          "expires_at": {
            "type": "string",
            "format": "date-time",
            "title": "Expires At"
          }
        },
        "type": "object",
        "required": [
          "id",
          "url",
          "expires_at"
        ],
        "title": "ExportInfo"
      },
      "FeedbackReaction": {
        "type": "string",
        "enum": [
          "LIKE",
          "DISLIKE"
        ],
        "title": "FeedbackReaction"
      },
      "FeedbackRequest": {
        "properties": {
          "is_adopted": {
            "type": "boolean",
            "title": "Is Adopted",
            "default": false
          },
          "reaction": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/FeedbackReaction"
              },
              {
                "type": "null"
              }
            ]
          }
        },
        "type": "object",
        "title": "FeedbackRequest"
      },
      "FeedbackResponse": {
        "properties": {
          "answer_id": {
            "type": "string",
            "format": "uuid",
            "title": "Answer Id"
          },
          "is_adopted": {
            "type": "boolean",
            "title": "Is Adopted"
          },
          "reaction": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/FeedbackReaction"
              },
              {
                "type": "null"
              }
            ]
          }
        },
        "type": "object",
        "required": [
          "answer_id",
          "is_adopted",
          "reaction"
        ],
        "title": "FeedbackResponse"
      },
      "HealthResponse": {
        "properties": {
          "status": {
            "type": "string",
            "title": "Status"
          },
          "version": {
            "type": "string",
            "title": "Version"
          }
        },
        "type": "object",
        "required": [
          "status",
          "version"
        ],
        "title": "HealthResponse"
      },
      "KnowledgeDocumentRequest": {
        "properties": {
          "path": {
            "type": "string",
            "title": "Path"
          },
          "content": {
            "type": "string",
            "title": "Content"
          }
        },
        "type": "object",
        "required": [
          "path",
          "content"
        ],
        "title": "KnowledgeDocumentRequest"
      },
      "KnowledgeDocumentResponse": {
        "properties": {
          "path": {
            "type": "string",
            "title": "Path"
          },
          "content": {
            "type": "string",
            "title": "Content"
          },
          "read_only": {
            "type": "boolean",
            "title": "Read Only"
          },
          "version": {
            "type": "string",
            "title": "Version"
          }
        },
        "type": "object",
        "required": [
          "path",
          "content",
          "read_only",
          "version"
        ],
        "title": "KnowledgeDocumentResponse"
      },
      "KnowledgeDocumentUpdateRequest": {
        "properties": {
          "content": {
            "type": "string",
            "title": "Content"
          }
        },
        "type": "object",
        "required": [
          "content"
        ],
        "title": "KnowledgeDocumentUpdateRequest"
      },
      "KnowledgeTreeNode": {
        "properties": {
          "name": {
            "type": "string",
            "title": "Name"
          },
          "path": {
            "type": "string",
            "title": "Path"
          },
          "node_type": {
            "type": "string",
            "enum": [
              "directory",
              "document"
            ],
            "title": "Node Type"
          },
          "read_only": {
            "type": "boolean",
            "title": "Read Only"
          },
          "size": {
            "type": "integer",
            "minimum": 0.0,
            "title": "Size"
          },
          "version": {
            "type": "string",
            "title": "Version"
          },
          "children": {
            "items": {
              "$ref": "#/components/schemas/KnowledgeTreeNode"
            },
            "type": "array",
            "title": "Children"
          }
        },
        "type": "object",
        "required": [
          "name",
          "path",
          "node_type",
          "read_only",
          "size",
          "version"
        ],
        "title": "KnowledgeTreeNode",
        "description": "虚拟知识库树的一个目录或文档节点。"
      },
      "KnowledgeTreeResponse": {
        "properties": {
          "roots": {
            "items": {
              "$ref": "#/components/schemas/KnowledgeTreeNode"
            },
            "type": "array",
            "title": "Roots"
          }
        },
        "type": "object",
        "required": [
          "roots"
        ],
        "title": "KnowledgeTreeResponse"
      },
      "MemoryCompressRequest": {
        "properties": {
          "merchant_id": {
            "type": "string",
            "format": "uuid",
            "title": "Merchant Id"
          },
          "category": {
            "$ref": "#/components/schemas/QuestionCategory"
          },
          "manual_markdown": {
            "type": "string",
            "maxLength": 20000,
            "title": "Manual Markdown",
            "default": ""
          }
        },
        "type": "object",
        "required": [
          "merchant_id",
          "category"
        ],
        "title": "MemoryCompressRequest",
        "description": "管理员手动重压某商家某分类的记忆。\n\n对应参考项目 ``WikiCompressRequest``：``manual_markdown`` 是人工补充内容，\n压缩时优先保留（见 ``app/prompts/memory.py`` 的提示词第 3 条）。"
      },
      "MemoryCompressResponse": {
        "properties": {
          "merchant_id": {
            "type": "string",
            "format": "uuid",
            "title": "Merchant Id"
          },
          "category": {
            "$ref": "#/components/schemas/QuestionCategory"
          },
          "content": {
            "type": "string",
            "title": "Content"
          },
          "history_rows": {
            "type": "integer",
            "title": "History Rows"
          },
          "degraded": {
            "type": "boolean",
            "title": "Degraded"
          },
          "degraded_reason": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Degraded Reason"
          }
        },
        "type": "object",
        "required": [
          "merchant_id",
          "category",
          "content",
          "history_rows",
          "degraded",
          "degraded_reason"
        ],
        "title": "MemoryCompressResponse"
      },
      "MetricDefinitionResponse": {
        "properties": {
          "metric_code": {
            "type": "string",
            "title": "Metric Code"
          },
          "display_name": {
            "type": "string",
            "title": "Display Name"
          },
          "unit": {
            "type": "string",
            "title": "Unit"
          },
          "definition": {
            "type": "string",
            "title": "Definition"
          },
          "sql_definition": {
            "type": "string",
            "title": "Sql Definition"
          },
          "dimensions": {
            "items": {
              "type": "string"
            },
            "type": "array",
            "title": "Dimensions"
          },
          "source_database": {
            "type": "string",
            "title": "Source Database"
          },
          "source_table": {
            "type": "string",
            "title": "Source Table"
          },
          "report_url": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Report Url"
          },
          "source": {
            "$ref": "#/components/schemas/MetricDefinitionSource"
          },
          "generated": {
            "type": "boolean",
            "title": "Generated"
          },
          "notice": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Notice"
          },
          "owner": {
            "type": "string",
            "title": "Owner"
          },
          "status": {
            "$ref": "#/components/schemas/MetricStatus"
          }
        },
        "type": "object",
        "required": [
          "metric_code",
          "display_name",
          "unit",
          "definition",
          "sql_definition",
          "dimensions",
          "source_database",
          "source_table",
          "report_url",
          "source",
          "generated",
          "notice",
          "owner",
          "status"
        ],
        "title": "MetricDefinitionResponse"
      },
      "MetricDefinitionSource": {
        "type": "string",
        "enum": [
          "METRIC_CATALOG",
          "FIELD_COMMENT",
          "AI_GENERATED"
        ],
        "title": "MetricDefinitionSource"
      },
      "MetricStatus": {
        "type": "string",
        "enum": [
          "ACTIVE",
          "DEPRECATED",
          "UNVERIFIED"
        ],
        "title": "MetricStatus"
      },
      "OpsStatusResponse": {
        "properties": {
          "llm_tokens_used_today": {
            "type": "integer",
            "title": "Llm Tokens Used Today"
          },
          "llm_tokens_remaining_today": {
            "type": "integer",
            "title": "Llm Tokens Remaining Today"
          },
          "llm_calls_today": {
            "type": "integer",
            "title": "Llm Calls Today"
          },
          "rate_limit_hits": {
            "type": "integer",
            "title": "Rate Limit Hits"
          },
          "degraded_count": {
            "type": "integer",
            "title": "Degraded Count"
          },
          "error_code_counts": {
            "additionalProperties": {
              "type": "integer"
            },
            "type": "object",
            "title": "Error Code Counts"
          },
          "agent_node_average_ms": {
            "additionalProperties": {
              "type": "number"
            },
            "type": "object",
            "title": "Agent Node Average Ms"
          },
          "demo_deployment_mode": {
            "type": "boolean",
            "title": "Demo Deployment Mode"
          }
        },
        "type": "object",
        "required": [
          "llm_tokens_used_today",
          "llm_tokens_remaining_today",
          "llm_calls_today",
          "rate_limit_hits",
          "degraded_count",
          "error_code_counts",
          "agent_node_average_ms",
          "demo_deployment_mode"
        ],
        "title": "OpsStatusResponse",
        "description": "系统级聚合快照，不含商家标识、Token 明文或 Prompt 内容。"
      },
      "QualityStatus": {
        "type": "string",
        "enum": [
          "PASSED",
          "DEGRADED",
          "FAILED",
          "NOT_RUN"
        ],
        "title": "QualityStatus"
      },
      "QueryPlanSummary": {
        "properties": {
          "summary": {
            "type": "string",
            "maxLength": 500,
            "minLength": 1,
            "title": "Summary"
          }
        },
        "type": "object",
        "required": [
          "summary"
        ],
        "title": "QueryPlanSummary"
      },
      "QuestionCategory": {
        "type": "string",
        "enum": [
          "PLATFORM_RULE",
          "TRADE",
          "REFUND",
          "CS_TICKET",
          "COMPENSATION",
          "COUPON",
          "GOODS",
          "MERCHANT_OTHER",
          "IDENTITY",
          "SCM",
          "UNKNOWN"
        ],
        "title": "QuestionCategory",
        "description": "商家问题的业务分类。\n\n逐字对应参考实现 `model/QuestionCategory.java`——业务域按 1:1 复刻，\nB3 的意图分类会直接路由到这些值，少一个就会出现无法归类的问题。\n枚举值是对外契约码，只能是英文；中文名见 `CATEGORY_DISPLAY_NAMES`。"
      },
      "ReadyResponse": {
        "properties": {
          "status": {
            "type": "string",
            "title": "Status"
          }
        },
        "type": "object",
        "required": [
          "status"
        ],
        "title": "ReadyResponse"
      },
      "Recommendation": {
        "properties": {
          "title": {
            "type": "string",
            "maxLength": 120,
            "minLength": 1,
            "title": "Title"
          },
          "evidence": {
            "type": "string",
            "maxLength": 500,
            "minLength": 1,
            "title": "Evidence"
          },
          "action": {
            "type": "string",
            "maxLength": 500,
            "minLength": 1,
            "title": "Action"
          }
        },
        "type": "object",
        "required": [
          "title",
          "evidence",
          "action"
        ],
        "title": "Recommendation"
      },
      "ThinkingStep": {
        "properties": {
          "label": {
            "type": "string",
            "maxLength": 120,
            "minLength": 1,
            "title": "Label"
          },
          "node": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_]{0,63}$",
            "title": "Node"
          }
        },
        "type": "object",
        "required": [
          "label",
          "node"
        ],
        "title": "ThinkingStep"
      },
      "Visualization": {
        "properties": {
          "enabled": {
            "type": "boolean",
            "title": "Enabled"
          },
          "type": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/ChartType"
              },
              {
                "type": "null"
              }
            ]
          },
          "allowed_types": {
            "items": {
              "$ref": "#/components/schemas/ChartType"
            },
            "type": "array",
            "title": "Allowed Types"
          },
          "title": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Title"
          },
          "dimension_key": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Dimension Key"
          },
          "metric_key": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Metric Key"
          },
          "unit": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Unit"
          },
          "data": {
            "items": {
              "additionalProperties": {
                "anyOf": [
                  {
                    "type": "string"
                  },
                  {
                    "type": "integer"
                  },
                  {
                    "type": "number"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            },
            "type": "array",
            "title": "Data"
          }
        },
        "type": "object",
        "required": [
          "enabled"
        ],
        "title": "Visualization"
      }
    },
    "securitySchemes": {
      "HTTPBearer": {
        "type": "http",
        "scheme": "bearer"
      }
    }
  }
}
```
