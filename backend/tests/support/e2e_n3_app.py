"""N3 商家工作台浏览器验收专用的确定性模型入口。"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI

from app.api.routes.v2 import merchant_chat as merchant_chat_route
from app.api.routes.v2 import shop_chat as shop_chat_route
from app.core.config import AppEnvironment, Settings
from app.llm.client import LlmMessage, LlmTurn
from app.main import create_app
from tests.support.e2e_s3_app import (
    S3_MERCHANT_ID,
    S3_MERCHANT_TOKEN,
    ScriptedS3Llm,
    _answer,
    _call,
    _latest_turn,
)

N3_PROMO_PRODUCT_ID = "00000000-0000-0000-0000-0000000053b2"


class ScriptedN3Llm(ScriptedS3Llm):
    @staticmethod
    def _next_turn(messages: Sequence[LlmMessage]) -> LlmTurn:
        question, results = _latest_turn(messages)
        if "给商品补上产地" in question:
            if results == 0:
                return _call("get_product_content", "n3-s2-content", product_id=N3_PROMO_PRODUCT_ID)
            if results == 1:
                return _call(
                    "draft_content_change", "n3-s2-draft", product_id=N3_PROMO_PRODUCT_ID,
                    attributes={"产地": {"value": "浙江", "source_type": "MERCHANT_STATED"}},
                )
            return _answer("已起草产地补充，请到审批页核对后批准。")
        if "为什么本周成交下滑" in question:
            today = datetime.now(UTC).date()
            if results == 0:
                return _call(
                    "query_metrics", "n3-s5-metric", metric="gross_gmv",
                    start=(today - timedelta(days=13)).isoformat(), end=today.isoformat(),
                )
            if results == 1:
                return _call("attribute_change", "n3-s5-attribute", metric="gross_gmv",
                             dimension="category")
            return _answer("本周成交额变化按类目归因；时间吻合只是线索，仍需核实原因。")
        if "给滞销商品起草九折券" in question:
            if results == 0:
                now = datetime.now(UTC)
                return _call(
                    "draft_coupon", "n3-s6-coupon", name="N3 九折券", kind="DISCOUNT",
                    discount_rate="0.10", product_ids=[N3_PROMO_PRODUCT_ID],
                    starts_at=(now - timedelta(minutes=1)).isoformat(),
                    ends_at=(now + timedelta(days=7)).isoformat(),
                )
            return _answer("已起草九折券，请到审批页核对后批准。")
        if "净成交额怎么算" in question:
            if results == 0:
                return _call("get_metric_definition", "n3-s7-definition", metric_code="net_gmv")
            if results == 1:
                return _call("search_rules", "n3-s7-rule", query="退货运费谁出")
            return _answer(
                "净成交额等于当期毛成交额减去当期退款金额。"
                "退货运费由平台承担，来源：平台规则/after_sale_freight.md。"
            )
        return ScriptedS3Llm._next_turn(messages)


def _scripted_llm(*_args: object, **_kwargs: object) -> ScriptedN3Llm:
    return ScriptedN3Llm()


class ScriptedN3CustomerLlm(ScriptedS3Llm):
    @staticmethod
    def _next_turn(messages: Sequence[LlmMessage]) -> LlmTurn:
        question, results = _latest_turn(messages)
        if "产地" in question:
            if results == 0:
                return _call(
                    "get_product_attribute", "n3-s2-origin", product_id=N3_PROMO_PRODUCT_ID,
                    attribute="产地",
                )
            returned = "\n".join(message.content for message in messages if message.role == "tool")
            return _answer(
                "产地是浙江。" if "浙江" in returned else "商家尚未提供产地，暂时无法确认。"
            )
        return _answer("请说说想了解哪件商品。")


def _customer_llm(*_args: object, **_kwargs: object) -> ScriptedN3CustomerLlm:
    return ScriptedN3CustomerLlm()


def create_app_from_env() -> FastAPI:
    merchant_chat_route.build_guarded_llm = _scripted_llm  # type: ignore[assignment]
    shop_chat_route.build_guarded_llm = _customer_llm  # type: ignore[assignment]
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=os.environ["S3_E2E_DATABASE_URL"],
        frontend_origin="http://127.0.0.1:5275",
        shop_origin="http://127.0.0.1:3275",
        demo_deployment_mode=True,
        demo_merchant_tokens={S3_MERCHANT_TOKEN: S3_MERCHANT_ID},
        demo_customer_identities={"borough-s3-e2e": "n3-e2e-buyer"},
        buyer_alias_secret="n3-e2e-buyer-alias-secret-0123456789",
        admin_token="n3-e2e-admin-token",
        rate_limit_per_minute=1000,
    )
    return create_app(settings)
