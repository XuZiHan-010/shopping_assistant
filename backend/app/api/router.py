"""汇总 `/api` 下的所有路由。"""

from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.demo import router as demo_router
from app.api.routes.exports import router as exports_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.health import router as health_router
from app.api.routes.metrics import router as metrics_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(demo_router)
api_router.include_router(chat_router)
api_router.include_router(exports_router)
api_router.include_router(feedback_router)
api_router.include_router(metrics_router)
