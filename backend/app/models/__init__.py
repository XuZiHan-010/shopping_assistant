"""导出所有 ORM 模型，供 Alembic 元数据加载。"""

from app.models.after_sales import (
    AfterSale,
    AfterSaleChallengePreview,
    AfterSaleLine,
    AfterSaleReply,
    AfterSaleSupplement,
)
from app.models.analytics import (
    Order,
    OrderItem,
    Product,
    Refund,
    ReturnRecord,
    SupportTicket,
)
from app.models.answer import Answer, Feedback
from app.models.cart import CartLine
from app.models.chatbi import ChatBiQaDaily
from app.models.conversation import Conversation, Message
from app.models.drafts import ChangeLedger, Draft
from app.models.events import AfterSaleEvent, FulfillmentEvent, InventoryEvent
from app.models.idempotency import IdempotencyRecord
from app.models.knowledge import KnowledgeDocument, MerchantMemory, MetricDefinition
from app.models.knowledge_index import KnowledgeChunk, KnowledgeIndexState, KnowledgeIndexVersion
from app.models.localization import MachineTranslationCache, ResourceLocalization
from app.models.mcp_credential import McpCredential
from app.models.memory_v2 import (
    CustomerMemory,
    CustomerMemoryPreference,
    CustomerSignal,
    DailyBrief,
    MemoryExtractionJob,
    MerchantMemoryFact,
    MerchantMemorySummary,
)
from app.models.merchant import Merchant
from app.models.operations import (
    AuditLog,
    ExportFile,
    LlmDailyBudget,
    LlmUsage,
    ModelPriceVersion,
    OperationEvidenceNonce,
    ScheduledJobRun,
)
from app.models.promotion import Coupon, GuardrailConfig
from app.models.provenance import ConversationProvenance
from app.models.session import AgentSession

__all__ = [
    "AfterSale",
    "AfterSaleChallengePreview",
    "AfterSaleEvent",
    "AfterSaleLine",
    "AfterSaleReply",
    "AfterSaleSupplement",
    "AgentSession",
    "Answer",
    "AuditLog",
    "CartLine",
    "ChangeLedger",
    "ChatBiQaDaily",
    "Conversation",
    "ConversationProvenance",
    "Coupon",
    "CustomerMemory",
    "CustomerMemoryPreference",
    "CustomerSignal",
    "DailyBrief",
    "Draft",
    "ExportFile",
    "Feedback",
    "FulfillmentEvent",
    "GuardrailConfig",
    "IdempotencyRecord",
    "InventoryEvent",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeIndexState",
    "KnowledgeIndexVersion",
    "LlmDailyBudget",
    "LlmUsage",
    "MachineTranslationCache",
    "McpCredential",
    "MemoryExtractionJob",
    "Merchant",
    "MerchantMemory",
    "MerchantMemoryFact",
    "MerchantMemorySummary",
    "Message",
    "MetricDefinition",
    "ModelPriceVersion",
    "OperationEvidenceNonce",
    "Order",
    "OrderItem",
    "Product",
    "Refund",
    "ResourceLocalization",
    "ReturnRecord",
    "ScheduledJobRun",
    "SupportTicket",
]
