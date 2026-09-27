"""N1-E Task 7 步骤 1–2：v1 冻结基线一侧的真实模型质量评测。

**本脚本会产生真实费用（AGENTS.md R3），默认不执行任何请求。**

- 不带 ``--yes``：只打印计划（用例数、最多调用次数、模型）就退出，不联网；
- 带 ``--yes``：逐条打印将要发出的调用，然后才发出；
- 只允许授权范围内的端点与模型（``https://api.deepseek.com`` / ``deepseek-flash``），
  即使 ``.env`` 里配置的是别的模型（例如已退役别名 ``deepseek-v4-flash``），
  本脚本也**强制覆盖**为 ``deepseek-flash``，不信任环境里的取值；
- 有硬性的总调用次数上限，超出即中止；
- 只测**双方共有的旧能力**（A2）：v1 商家 Chat 是当前唯一现成的真实端到端链路，
  Task 7 步骤 3（与新工具循环对照）要等 N2 落地才能执行，本脚本不做。

用法::

    cd backend
    uv run python -m scripts.eval_quality_smoke
    uv run python -m scripts.eval_quality_smoke --yes

结果落 ``docs/history/eval/n1-quality-baseline-<date>.md``：只含模型、思考模式、调用次数、
token、门禁与裁判结论。**不记录 API Key，不记录完整请求体**。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.eval.cases import EvalCase, load_cases_from_directory
from app.eval.graders.assertions import AssertionContext
from app.eval.report import CaseReportEntry, DatasetReport, QualityMetrics, render_report
from app.eval.runner import ExecutionOutcome, QualityRunner, RubricSpec
from app.llm.deepseek import DeepSeekLlmClient
from app.main import create_app
from app.models.merchant import Merchant
from app.services.seed_service import default_merchants

# ---- R3 授权范围：换其中任何一项都须重新取得用户同意 -------------------------------------
AUTHORIZED_BASE_URL = "https://api.deepseek.com"
AUTHORIZED_MODEL = "deepseek-flash"
#: 单条用例内部：Chat 请求最多 10 次子调用（生产硬顶 `llm_max_calls_per_request`）
#: + 1 次裁判 = 11；6 条合计不得超过这个数。
MAX_TOTAL_CALLS = 66
SEED_DAYS = 180

QUALITY_DATASET_DIR = (
    Path(__file__).resolve().parents[1] / "app" / "eval" / "datasets" / "quality"
)
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "history" / "eval"

RUBRICS: dict[str, RubricSpec] = {
    "answer_quality": RubricSpec(
        version="v1",
        prompt=(
            "评估这段经营指标问答的质量，只依据下面给出的对话文本本身，不要假设它来自"
            "何种系统实现。打分维度：回答是否直接回应了问题、是否给出了具体数字或数据、"
            "语言是否通顺、是否符合对话记录声明的显示语言。"
            "0.0 = 完全没有回应或答非所问；1.0 = 直接、具体、语言通顺、语言正确。"
        ),
    ),
    "greeting_quality": RubricSpec(
        version="v1",
        prompt=(
            "评估这段问候语回复的质量：是否礼貌、是否符合对话记录声明的显示语言、"
            "是否简洁不啰嗦。0.0 = 不礼貌或语言不对；1.0 = 礼貌、简洁、语言正确。"
        ),
    ),
}


class BudgetExceededError(RuntimeError):
    """总调用次数即将超过授权上限，中止而不是多发一次。"""


class _CallMeter:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.made = 0

    def before_call(self, label: str) -> None:
        if self.made >= self.limit:
            raise BudgetExceededError(f"已达计划调用次数上限 {self.limit}，中止：{label}")
        self.made += 1
        print(f"  → 即将发出第 {self.made}/{self.limit} 次调用：{label}", flush=True)


@dataclass
class _RunContext:
    app: FastAPI
    bearer_token: str
    meter: _CallMeter


class _MeteredJudgeClient:
    """把真实 `DeepSeekLlmClient` 包一层，接入总调用计数与逐条打印。"""

    def __init__(self, inner: DeepSeekLlmClient, meter: _CallMeter) -> None:
        self._inner = inner
        self._meter = meter

    def is_configured(self) -> bool:
        return self._inner.is_configured()

    async def complete(self, **kwargs: Any) -> Any:
        self._meter.before_call("裁判打分")
        return await self._inner.complete(**kwargs)


async def _ensure_demo_merchants(session: AsyncSession) -> None:
    """`seed_analytics()` 要求商家集合**恰好**是三个演示商家（不多不少）。

    本地测试库在集成测试之间会留下无关的一次性商家行（例如
    `tests/conftest.py` 的 `MERCHANT_ONE_ID`），先清空 `merchants`（CASCADE
    带走一切引用它的经营数据行）再插入演示三商家，而不是只补齐缺失的——
    否则「集合不匹配」会在插入之后依然成立。
    """

    await session.execute(text("TRUNCATE TABLE merchants CASCADE"))
    for merchant in default_merchants():
        session.add(
            Merchant(
                id=merchant.id,
                merchant_code=merchant.merchant_code,
                display_name=merchant.display_name,
                display_name_en=merchant.display_name_en,
            )
        )
    await session.flush()


async def _reseed_demo_analytics(settings: Settings) -> int:
    """复用已验证的 `scripts.seed_demo_analytics` 核心逻辑，保证问题有真实数据可答。"""

    from app.analytics.dates import business_today
    from app.analytics.seed_safety import assert_local_database_url, reject_production
    from scripts.seed_demo_analytics import seed_analytics

    assert_local_database_url(settings.database_url)
    reject_production(settings)
    end_date = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    database = Database(settings)
    try:
        async with database.session() as session:
            await _ensure_demo_merchants(session)
            written = await seed_analytics(session, days=SEED_DAYS, end_date=end_date)
            await session.commit()
        return written
    finally:
        await database.dispose()


def _bearer_token_for_merchant_100(settings: Settings) -> str:
    target_id = default_merchants()[0].id
    for token, merchant_id in settings.demo_merchant_tokens.items():
        if merchant_id == target_id:
            return token
    raise RuntimeError("DEMO_MERCHANT_TOKENS 未配置 borough-demo-100 对应的 Token")


async def _execute_case(case: EvalCase, ctx: _RunContext) -> ExecutionOutcome:
    turn = case.turns[0]
    assert turn.request is not None
    message = (turn.request.json_body or {}).get("message", "")
    headers = {
        **turn.request.headers,
        "Authorization": f"Bearer {ctx.bearer_token}",
        "Accept": "application/json",
    }
    ctx.meter.before_call(f"{case.id}：Chat（{turn.request.headers.get('Accept-Language')}）")
    async with AsyncClient(
        transport=ASGITransport(app=ctx.app), base_url="http://testserver"
    ) as client:
        response = await client.request(
            turn.request.method,
            turn.request.path,
            headers=headers,
            json=turn.request.json_body,
        )
    body: dict[str, Any] = response.json() if response.content else {}
    answer = body.get("answer", "")
    transcript = (
        f"[显示语言 {case.locale}]\n"
        f"用户：{message}\n"
        f"助手：{answer}"
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
    )


async def run_quality_baseline(settings: Settings) -> DatasetReport:
    cases = load_cases_from_directory(QUALITY_DATASET_DIR)
    meter = _CallMeter(MAX_TOTAL_CALLS)

    written = await _reseed_demo_analytics(settings)
    print(f"已重新灌入 {written} 行演示经营数据（{SEED_DAYS} 天）")

    database = Database(settings)
    app = create_app(settings, database=database)
    bearer_token = _bearer_token_for_merchant_100(settings)
    ctx = _RunContext(app=app, bearer_token=bearer_token, meter=meter)

    judge_client = _MeteredJudgeClient(DeepSeekLlmClient(settings), meter)
    runner = QualityRunner(
        executor=lambda case: _execute_case(case, ctx),
        judge_client=judge_client,
        rubrics=RUBRICS,
    )

    entries: list[CaseReportEntry] = []
    try:
        for case in cases:
            print(f"用例 {case.id}（{case.locale}）", flush=True)
            result = await runner.run(case, candidate="v1-frozen-baseline")
            detail = result.failure_detail
            if result.judge is not None:
                detail = (
                    f"裁判分数 {result.judge.score:.2f}"
                    f"（rubric={result.judge.rubric_id}@{result.judge.rubric_version}）"
                )
            entries.append(
                CaseReportEntry(case_id=case.id, passed=result.passed, failure_detail=detail)
            )
            print(f"  = {'PASS' if result.passed else 'FAIL'}：{detail}", flush=True)
    finally:
        await database.dispose()

    return DatasetReport(security_results=entries, quality_metrics=QualityMetrics())


def _print_plan() -> None:
    cases = load_cases_from_directory(QUALITY_DATASET_DIR)
    print(f"接口：DeepSeek OpenAI 兼容协议（根地址 {AUTHORIZED_BASE_URL}）")
    print(f"模型：{AUTHORIZED_MODEL}（强制覆盖 .env 里的取值）；思考模式：disabled")
    print(f"计划：{len(cases)} 个用例，最多 {MAX_TOTAL_CALLS} 次调用")
    for case in cases:
        print(f"  - {case.id}（{case.locale}，rubric={case.rubric_id}）")
    print("范围：只测 v1 冻结基线（步骤 1–2）；步骤 3 的对照评测需 N2 工具循环，本脚本不做。")


def build_settings() -> Settings:
    base = get_settings()
    return base.model_copy(
        update={
            "llm_base_url": AUTHORIZED_BASE_URL,
            "llm_model": AUTHORIZED_MODEL,
            "llm_thinking": "disabled",
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="N1 Task 7 真实模型质量评测（会产生真实费用）")
    parser.add_argument("--yes", action="store_true", help="确认发出真实请求；缺省只展示计划")
    args = parser.parse_args(argv)

    _print_plan()
    if not args.yes:
        print("\n未加 --yes：以上只是计划，没有发出任何请求。")
        return 0

    settings = build_settings()
    if settings.llm_base_url.rstrip("/") != AUTHORIZED_BASE_URL:
        print(f"拒绝运行：LLM_BASE_URL 必须是 {AUTHORIZED_BASE_URL}", file=sys.stderr)
        return 2
    if settings.llm_model != AUTHORIZED_MODEL:
        print(f"拒绝运行：LLM_MODEL 必须是 {AUTHORIZED_MODEL}", file=sys.stderr)
        return 2
    if not settings.llm_api_key:
        print("拒绝运行：未配置 LLM_API_KEY", file=sys.stderr)
        return 2

    configure_event_loop_policy()
    when = datetime.now()
    try:
        report = asyncio.run(run_quality_baseline(settings))
    except BudgetExceededError as error:
        print(f"\n中止：{error}", file=sys.stderr)
        return 3

    rendered = render_report(
        report, gate_title="v1 冻结基线质量结果（不是安全门禁；仅记录，不阻断）"
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"n1-quality-baseline-{when:%Y-%m-%d}.md"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(rendered.text + "\n")
    print(f"\n结果已写入 {path}")
    print(f"门禁结论（本报告的 gate_passed，即『全部用例通过』）：{rendered.gate_passed}")
    return 0 if rendered.gate_passed else 1


if __name__ == "__main__":
    sys.exit(main())
