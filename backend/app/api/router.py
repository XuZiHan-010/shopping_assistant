"""汇总 `/api` 下的所有路由。"""

from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.chat import router as chat_router
from app.api.routes.demo import router as demo_router
from app.api.routes.exports import router as exports_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.reports import admin_router as reports_admin_router
from app.api.routes.reports import router as reports_router
from app.api.routes.v2.merchant_after_sales import router as merchant_after_sales_router
from app.api.routes.v2.merchant_brief import router as merchant_brief_router
from app.api.routes.v2.merchant_catalog import router as merchant_catalog_router
from app.api.routes.v2.merchant_chat import router as merchant_chat_router
from app.api.routes.v2.merchant_conversations import router as merchant_conversations_router
from app.api.routes.v2.merchant_drafts import router as merchant_drafts_router
from app.api.routes.v2.merchant_feedback import router as merchant_feedback_router
from app.api.routes.v2.merchant_inventory import router as merchant_inventory_router
from app.api.routes.v2.merchant_sessions import router as merchant_sessions_router
from app.api.routes.v2.merchant_signals import router as merchant_signals_router
from app.api.routes.v2.shop_after_sales import router as shop_after_sales_router
from app.api.routes.v2.shop_cart import router as shop_cart_router
from app.api.routes.v2.shop_catalog import router as shop_catalog_router
from app.api.routes.v2.shop_chat import router as shop_chat_router
from app.api.routes.v2.shop_conversations import router as shop_conversations_router
from app.api.routes.v2.shop_orders import router as shop_orders_router
from app.api.routes.v2.shop_sessions import router as shop_sessions_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(demo_router)
api_router.include_router(chat_router)
api_router.include_router(exports_router)
api_router.include_router(feedback_router)
api_router.include_router(metrics_router)
api_router.include_router(reports_router)
# N1 内唯一落地的 v2 路由：5 条会话签发/绑定/注销端点（模块 D Task 7）。
api_router.include_router(shop_sessions_router)
api_router.include_router(merchant_sessions_router)
# N2 模块 D（会话目录与反馈）：商家回答反馈与双端会话目录。
api_router.include_router(merchant_feedback_router)
api_router.include_router(merchant_conversations_router)
api_router.include_router(shop_conversations_router)
api_router.include_router(merchant_inventory_router)
api_router.include_router(merchant_catalog_router)
api_router.include_router(merchant_after_sales_router)
api_router.include_router(merchant_signals_router)
api_router.include_router(merchant_drafts_router)
api_router.include_router(merchant_brief_router)
api_router.include_router(merchant_chat_router)
# N2 模块 B Task 1：顾客端店铺、商品与券的公开浏览。
api_router.include_router(shop_catalog_router)
api_router.include_router(shop_cart_router)
api_router.include_router(shop_orders_router)
api_router.include_router(shop_after_sales_router)
api_router.include_router(shop_chat_router)

# 这些路由仅在已配置 ADMIN_TOKEN 时由应用工厂挂载。
admin_routers = (admin_router, knowledge_router, analytics_router, reports_admin_router)
