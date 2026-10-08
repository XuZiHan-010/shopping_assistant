"""N5 质量集真实运行入口；只在已获 R3 授权后显式 ``--real`` 执行。

逐次上游调用由独立证据账本预留，325 次 / 50 万 token 是硬上限。
用例只在本地可丢弃 ``_test`` 库执行；输出保留合成对话供人工复核，
自动裁判只评可见回答，不能代替来源忠实度与副作用的人工检查。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.analytics.dates import business_today
from app.core.config import Settings
from app.core.security import MerchantContext
from app.db.session import Database
from app.eval.acceptance_evidence import (
    EvidenceBatch,
    append_evidence,
    prepare_output,
    validate_settings,
)
from app.eval.acceptance_recovery import RecoveryBatch
from app.eval.cases import EvalCase, load_cases_from_directory
from app.eval.graders.assertions import AssertionContext
from app.eval.runner import ExecutionOutcome, QualityRunner, RubricSpec
from app.knowledge.wiki_seed import seed_wiki_documents
from app.llm.client import LlmCallOptions
from app.llm.deepseek import DeepSeekLlmClient
from app.main import create_app
from app.repositories.session import SessionRepository
from app.services.seed_service import default_merchants

DATASET = Path(__file__).resolve().parent / "datasets" / "quality"
CASE_COUNT = 25
MAX_CALLS = 325
MAX_TOKENS = 500_000
SEED_DAYS = 180

RUBRICS = {
    "answer_quality": RubricSpec(
        version="n5-v1",
        prompt=(
            "仅评价可见回答：是否直接回应提问、符合指定语言、清楚标明不确定性；"
            "访客涉及本人订单或记忆时，是否引导先绑定演示顾客；要求规则出处时，"
            "是否给出可识别的出处。不可从回答文字推断工具调用或数据真实性。"
            "0 为答非所问或误导，1 为完全符合。"
        ),
    ),
    "greeting_quality": RubricSpec(
        version="n5-v1",
        prompt="只评价问候是否简洁、礼貌、符合指定语言。0 为不合格，1 为完全符合。",
    ),
}

_case_id: ContextVar[str] = ContextVar("n5_real_case_id", default="unassigned")


def quality_cases() -> list[EvalCase]:
    cases = [
        *load_cases_from_directory(DATASET),
        *load_cases_from_directory(DATASET / "scenarios"),
    ]
    counts = Counter(case.introduced_in for case in cases)
    if len(cases) != CASE_COUNT or counts != {"N1": 6, "N2": 4, "N3": 7, "N5": 8}:
        raise ValueError("质量集数量或里程碑分层改变，须重新核对费用授权")
    for case in cases:
        requests = [turn for turn in case.turns if turn.request is not None]
        if len(requests) != 1 or requests[0] is not case.turns[-1]:
            raise ValueError(f"{case.id} 不再是单个最终聊天请求")
        if any(
            turn.primitive is not None and turn.primitive.name != "session.bind_actor"
            for turn in case.turns[:-1]
        ):
            raise ValueError(f"{case.id} 有未经核对的准备动作")
    return cases


class MeteredDeepSeek:
    """每次真实上游调用分配唯一账本 ID，绝不把 HTTP 回合误当模型次数。"""

    def __init__(
        self,
        inner: DeepSeekLlmClient,
        batch: EvidenceBatch,
        settings: Settings,
        *,
        judge: bool = False,
    ):
        self.inner, self.batch, self.settings = inner, batch, settings
        self.judge = judge

    def is_configured(self) -> bool:
        return self.inner.is_configured()

    def _one_call(self) -> Any:
        # Chat 与裁判各有客户端实例；局部计数器会让同一用例撞 ID。
        # UUID 只标识调用，次数与 token 仍由同一持久账本强制限制。
        request_id = f"n5-quality:{_case_id.get()}:{uuid4().hex}"
        return self.batch.client(
            self.inner,
            request_id,
            max_output_tokens=self.settings.llm_max_output_tokens_per_call,
        )

    async def complete(self, **kwargs: Any) -> Any:
        if self.judge:
            kwargs["options"] = LlmCallOptions(thinking="disabled")
        return await self._one_call().complete(**kwargs)

    async def converse(self, **kwargs: Any) -> Any:
        return await self._one_call().converse(**kwargs)


@dataclass(frozen=True)
class _Actor:
    token: str | None
    bearer: str | None


async def _actor(case: EvalCase, database: Database, settings: Settings) -> _Actor:
    merchant = default_merchants()[0]
    bearer = next(
        (
            token
            for token, merchant_id in settings.demo_merchant_tokens.items()
            if merchant_id == merchant.id
        ),
        None,
    )
    if bearer is None:
        raise ValueError("缺少默认演示商家的服务端 Token 映射")
    if case.introduced_in == "N1":
        return _Actor(token=None, bearer=bearer)
    async with database.session() as session:
        repo = SessionRepository(session, default_ttl_seconds=settings.session_ttl_seconds)
        if case.role == "MERCHANT":
            token, _ = await repo.issue_merchant(
                MerchantContext(merchant_id=merchant.id), issuer=bearer
            )
        else:
            token, ctx = await repo.issue_customer_guest(
                merchant_id=merchant.id, shop_slug=merchant.merchant_code
            )
            for turn in case.turns[:-1]:
                if turn.primitive is not None:
                    await repo.bind_demo_customer(
                        ctx, buyer_key=str(turn.primitive.args["buyer_key"])
                    )
        await session.commit()
    return _Actor(token=token, bearer=None)


async def _execute_case(
    case: EvalCase, app: FastAPI, database: Database, settings: Settings
) -> ExecutionOutcome:
    actor = await _actor(case, database, settings)
    request = case.turns[-1].request
    assert request is not None
    message = str((request.json_body or {})["message"])
    request_id = f"n5-quality:{case.id}"
    headers = {
        **request.headers,
        "Accept-Language": case.locale,
        "Accept": "application/json",
        "X-Request-Id": request_id,
    }
    if actor.bearer:
        headers["Authorization"] = f"Bearer {actor.bearer}"
    else:
        headers["X-Session-Id"] = str(actor.token)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.request(
            request.method,
            request.path,
            headers=headers,
            params=request.query,
            json=request.json_body,
        )
    body = response.json() if response.content else {}
    if not isinstance(body, dict):
        body = {}
    transcript = (
        f"[显示语言 {case.locale}]\n用户：{message}\n助手：{body.get('answer', '')}"
    )
    return ExecutionOutcome(
        assertion_context=AssertionContext(
            status_code=response.status_code,
            code=body.get("code"),
            audit_events=(),
            side_effects={},
            response_body=body,
        ),
        transcript=transcript,
        request_id=request_id,
    )


async def _seed(database: Database, settings: Settings) -> None:
    from sqlalchemy import text

    from app.models.merchant import Merchant
    from scripts.seed_demo_analytics import seed_analytics
    from scripts.seed_demo_scenarios import seed_scenarios

    day = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    async with database.session() as session:
        await session.execute(text("TRUNCATE TABLE merchants CASCADE"))
        session.add_all(
            Merchant(
                id=merchant.id,
                merchant_code=merchant.merchant_code,
                display_name=merchant.display_name,
                display_name_en=merchant.display_name_en,
            )
            for merchant in default_merchants()
        )
        await session.flush()
        await seed_analytics(session, days=SEED_DAYS, end_date=day)
        await seed_scenarios(session, business_day=day)
        await session.commit()
    await seed_wiki_documents(database)


async def run_real(
    settings: Settings,
    *,
    output: Path,
    ledger: Path,
    fresh_output_existing_ledger: bool = False,
    case_ids: frozenset[str] | None = None,
) -> None:
    validate_settings(settings)
    cases = quality_cases()
    if case_ids is not None:
        unknown = case_ids - {case.id for case in cases}
        if unknown:
            raise ValueError(f"未知质量用例：{', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in case_ids]
    if output.exists() and not ledger.exists():
        raise FileExistsError("已有结果却没有计费账本，禁止继续")
    if ledger.exists() and not output.exists() and not fresh_output_existing_ledger:
        raise FileExistsError("沿用已有计费账本开启新评测须显式指定该操作")
    completed: list[str] = []
    if output.exists():
        rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        if not rows or rows[0] != {"status": "PREPARED", "complete": False}:
            raise ValueError("结果文件头无效，禁止自动续跑")
        if any(row.get("status") == "COMPLETE" for row in rows[1:]):
            raise ValueError("评测批次已完成，禁止自动重跑")
        completed = [str(row["case_id"]) for row in rows[1:]]
        if completed != [case.id for case in cases[: len(completed)]]:
            raise ValueError("已有结果不是数据集前缀，禁止自动续跑")
    database = Database(settings)
    try:
        await _seed(database, settings)
        if not output.exists():
            prepare_output(output)
        batch = RecoveryBatch(ledger, max_calls=MAX_CALLS, max_tokens=MAX_TOKENS)
        batch.configure(settings)
        app = create_app(settings, database=database)
        def metered_factory(_settings: Settings) -> MeteredDeepSeek:
            return MeteredDeepSeek(DeepSeekLlmClient(_settings), batch, _settings)

        judge_settings = settings.model_copy(update={"llm_max_output_tokens_per_call": 512})
        judge = MeteredDeepSeek(
            DeepSeekLlmClient(judge_settings), batch, judge_settings, judge=True
        )
        transcripts: dict[str, str] = {}

        async def execute(case: EvalCase) -> ExecutionOutcome:
            outcome = await _execute_case(case, app, database, settings)
            transcripts[case.id] = outcome.transcript
            return outcome

        runner = QualityRunner(
            executor=execute,
            judge_client=judge,
            rubrics=RUBRICS,
        )
        with patch("app.api.dependencies.DeepSeekLlmClient", side_effect=metered_factory):
            for case in cases[len(completed) :]:
                reset = _case_id.set(case.id)
                try:
                    result = await runner.run(case)
                finally:
                    _case_id.reset(reset)
                append_evidence(
                    output,
                    {
                        "case_id": case.id,
                        "passed": result.passed,
                        "failure_detail": result.failure_detail,
                        "judge_score": result.judge.score if result.judge else None,
                        "rubric_version": result.judge.rubric_version if result.judge else None,
                        "request_id": result.request_id,
                        "transcript": transcripts[case.id],
                    },
                )
                print(f"{case.id}: {'PASS' if result.passed else 'FAIL'}", flush=True)
        append_evidence(output, {"status": "COMPLETE", "cases": len(cases)})
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="N5 真实质量评测；会产生 DeepSeek 费用")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument(
        "--case-id", action="append", default=None,
        help="仅复核指定冻结用例；多条可重复传入，仍沿用同一授权账本",
    )
    parser.add_argument(
        "--fresh-output-existing-ledger", action="store_true",
        help="修复后另开结果文件，继续由既有账本统一扣减本次授权总上限",
    )
    args = parser.parse_args()
    cases = quality_cases()
    selected = [case for case in cases if not args.case_id or case.id in args.case_id]
    print(
        f"DeepSeek OpenAI / deepseek-flash；{len(selected)} 回合；"
        f"最多 {MAX_CALLS} 次、{MAX_TOKENS} token"
    )
    if not args.real:
        print("未指定 --real，未发送请求")
        return
    from app.core.runtime import configure_event_loop_policy

    configure_event_loop_policy()
    asyncio.run(
        run_real(
            Settings(), output=args.output, ledger=args.ledger,
            fresh_output_existing_ledger=args.fresh_output_existing_ledger,
            case_ids=frozenset(args.case_id) if args.case_id else None,
        )
    )


if __name__ == "__main__":
    main()
