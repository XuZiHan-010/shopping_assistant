"""v1 两阶段意图识别准确率评测；真实模式须经 R3 费用授权后手动运行。

被测对象是冻结基线里的 `IntentService`，本模块只调用、不修改它：

- **第一阶段** `recognize`：回答模式与业务域（最多 2 次模型调用，含一次规则纠偏重试）；
- **第二阶段** `understand`：结构化查询意图，经白名单校验（最多 3 次）。

零 LLM 前置闸门不在范围内：它按知识文档、正式指标目录与商家记忆打分，离线评测里没有后两者，
在这里跑只会低估放行率。业务索引取自团队维护知识的种子，与线上 `load_index()` 的主体一致。

报告只含聚合数与用例 ID；逐例结果另存本地，模型原始响应在批次账本里。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final, Protocol

import yaml

from app.intent.service import IntentService
from app.llm.client import LlmBudget, LlmCallOptions, LlmClient, LlmResult

DATASET: Final = Path(__file__).parent / "datasets/intent/v1_intent_cases.yaml"
EXPECTED_CASES: Final = 80
#: 分类最多 2 次 + 结构化理解最多 3 次（`IntentService` 的重试上限）。
MAX_CALLS_PER_CASE: Final = 5
#: 日期标注的换算基准；改动它必须同步重标问题集里的 `date`。
TODAY: Final = date(2026, 10, 8)
_CASE_BUDGET_TOKENS: Final = 30_000
_BATCH_MAX_TOKENS: Final = 900_000

LlmFactory = Callable[[str], LlmClient]


def load_cases(path: Path = DATASET) -> list[dict[str, Any]]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("意图问题集必须是列表")
    return cases


class _CountingClient:
    """只数调用次数：真实客户端没有 Fake 的 `calls` 记录。"""

    def __init__(self, inner: LlmClient) -> None:
        self._inner = inner
        self.calls = 0

    def is_configured(self) -> bool:
        return self._inner.is_configured()

    async def complete(self, **kwargs: Any) -> LlmResult:
        self.calls += 1
        return await self._inner.complete(**kwargs)


def _score(correct: int, total: int) -> dict[str, Any]:
    return {"correct": correct, "total": total, "rate": correct / total if total else 1.0}


async def evaluate(
    cases: Sequence[Mapping[str, Any]],
    *,
    llm_for_case: LlmFactory,
    index_text: str,
    today: date,
    on_case: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """逐条跑两阶段识别并与标注比对。严格 = 只认首选标签，宽松 = 认全部可接受标签。"""
    tallies = dict.fromkeys(
        (
            "s1_mode_strict",
            "s1_mode_lenient",
            "s1_category_strict",
            "s1_category_lenient",
            "s1_joint",
            "s1_analyzed",
            "final_mode_strict",
            "final_mode_lenient",
            "final_joint",
            "degraded",
            "metric_total",
            "metric_correct",
            "date_total",
            "date_correct",
            "calls",
        ),
        0,
    )
    failed: dict[str, list[str]] = {"stage1": [], "final": [], "metric": [], "date": []}
    groups: dict[str, dict[str, int]] = {}

    for case in cases:
        case_id = str(case["id"])
        modes, categories = list(case["mode"]), list(case["category"])
        client = _CountingClient(llm_for_case(case_id))
        service = IntentService(client)
        budget = LlmBudget(max_calls=MAX_CALLS_PER_CASE, max_tokens=_CASE_BUDGET_TOKENS)

        initial = await service.recognize(str(case["question"]), index_text, budget)
        outcome = await service.understand(
            str(case["question"]), initial, index_text, budget, today
        )
        intent = outcome.intent

        s1_mode, s1_category = initial.answer_mode.value, initial.category.value
        s1_joint = initial.llm_analyzed and s1_mode in modes and s1_category in categories
        final_mode, final_category = intent.answer_mode.value, intent.category.value
        final_joint = not outcome.degraded and final_mode in modes and final_category in categories
        verdict: dict[str, bool] = {"stage1": s1_joint, "final": final_joint}

        tallies["calls"] += client.calls
        tallies["s1_analyzed"] += initial.llm_analyzed
        tallies["s1_mode_strict"] += initial.llm_analyzed and s1_mode == modes[0]
        tallies["s1_mode_lenient"] += initial.llm_analyzed and s1_mode in modes
        tallies["s1_category_strict"] += initial.llm_analyzed and s1_category == categories[0]
        tallies["s1_category_lenient"] += initial.llm_analyzed and s1_category in categories
        tallies["s1_joint"] += s1_joint
        tallies["final_mode_strict"] += not outcome.degraded and final_mode == modes[0]
        tallies["final_mode_lenient"] += not outcome.degraded and final_mode in modes
        tallies["final_joint"] += final_joint
        tallies["degraded"] += outcome.degraded
        if not s1_joint:
            failed["stage1"].append(case_id)
        if not final_joint:
            failed["final"].append(case_id)

        if "metric" in case:
            verdict["metric"] = intent.metric in case["metric"]
            tallies["metric_total"] += 1
            tallies["metric_correct"] += verdict["metric"]
            if not verdict["metric"]:
                failed["metric"].append(case_id)
        if "date" in case:
            actual = (
                [intent.date_range.start.isoformat(), intent.date_range.end.isoformat()]
                if intent.date_range is not None
                else None
            )
            verdict["date"] = actual in [list(pair) for pair in case["date"]]
            tallies["date_total"] += 1
            tallies["date_correct"] += verdict["date"]
            if not verdict["date"]:
                failed["date"].append(case_id)

        group = groups.setdefault(str(case["group"]), {"total": 0, "stage1": 0, "final": 0})
        group["total"] += 1
        group["stage1"] += s1_joint
        group["final"] += final_joint

        if on_case is not None:
            on_case(
                {
                    "id": case_id,
                    "group": case["group"],
                    "calls": client.calls,
                    "stage1": {
                        "answer_mode": s1_mode,
                        "category": s1_category,
                        "llm_analyzed": initial.llm_analyzed,
                        "degraded_reason": initial.degraded_reason,
                    },
                    "final": {
                        "intent": intent.model_dump(mode="json", exclude_none=True),
                        "degraded": outcome.degraded,
                        "degraded_reason": outcome.degraded_reason,
                        "notes": list(outcome.notes),
                        "adjusted": list(outcome.validation.adjusted),
                        "rejected": list(outcome.validation.rejected),
                    },
                    "verdict": verdict,
                }
            )

    total = len(cases)
    return {
        "cases": total,
        "calls": tallies["calls"],
        "stage1": {
            "analyzed": tallies["s1_analyzed"],
            "mode_strict": _score(tallies["s1_mode_strict"], total),
            "mode_lenient": _score(tallies["s1_mode_lenient"], total),
            "category_strict": _score(tallies["s1_category_strict"], total),
            "category_lenient": _score(tallies["s1_category_lenient"], total),
            "joint": _score(tallies["s1_joint"], total),
        },
        "final": {
            "mode_strict": _score(tallies["final_mode_strict"], total),
            "mode_lenient": _score(tallies["final_mode_lenient"], total),
            "joint": _score(tallies["final_joint"], total),
            "degraded": tallies["degraded"],
        },
        "metric": _score(tallies["metric_correct"], tallies["metric_total"]),
        "date": _score(tallies["date_correct"], tallies["date_total"]),
        "by_group": {
            name: {
                "total": group["total"],
                "stage1_joint": group["stage1"],
                "final_joint": group["final"],
            }
            for name, group in sorted(groups.items())
        },
        "failed": failed,
        "note": (
            "joint = 回答模式与业务域同时落在可接受标签内（宽松口径）。标签由评测作者一人标注；"
            "单次运行，未估计模型输出的随机波动；前置闸门不在范围内。"
        ),
    }


class _Batch(Protocol):
    def client(self, inner: Any, request_id: str, *, max_output_tokens: int) -> Any: ...


class PerCallClient:
    """每次调用换一个账本请求号。

    批次账本禁止同一个 `request_id` 预留两次（防止自动重跑），而一条用例最多调用 5 次模型，
    所以按 `<前缀>:<序号>` 逐次取号，内层费用守卫也逐次新建以保持用量台账一一对应。
    """

    def __init__(
        self,
        batch: _Batch,
        make_inner: Callable[[str], LlmClient],
        prefix: str,
        *,
        max_output_tokens: int,
    ) -> None:
        self._batch, self._make_inner = batch, make_inner
        self._prefix, self._max_output_tokens = prefix, max_output_tokens
        self._calls = 0

    def is_configured(self) -> bool:
        return True

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
        options: LlmCallOptions | None = None,
    ) -> LlmResult:
        self._calls += 1
        request_id = f"{self._prefix}:{self._calls}"
        client = self._batch.client(
            self._make_inner(request_id), request_id, max_output_tokens=self._max_output_tokens
        )
        kwargs: dict[str, Any] = {
            "system": system,
            "user": user,
            "fallback": fallback,
            "budget": budget,
        }
        if options is not None:
            kwargs["options"] = options
        result: LlmResult = await client.complete(**kwargs)
        return result


async def _run_real(dump: Path, ledger: Path) -> None:
    # 真实运行才需要的依赖放在这里导入：Fake 评测不该为了算准确率而加载数据库与知识种子。
    from app.api.dependencies import build_guarded_llm
    from app.core.config import Settings
    from app.db.session import Database
    from app.eval.acceptance_evidence import (
        EvidenceBatch,
        append_evidence,
        prepare_output,
        validate_settings,
    )
    from app.eval.rag_e5 import _SEED
    from app.knowledge.retrieval import KnowledgeRetrieval

    settings = Settings()
    validate_settings(settings)
    cases = load_cases()
    if len(cases) != EXPECTED_CASES:
        raise ValueError("意图问题集数量已变化，需重新取得费用授权")
    prepare_output(dump)
    batch = EvidenceBatch(
        ledger, max_calls=EXPECTED_CASES * MAX_CALLS_PER_CASE, max_tokens=_BATCH_MAX_TOKENS
    )
    batch.configure(settings)
    index = await KnowledgeRetrieval(_SEED).load_index()
    database = Database(settings)
    try:
        report = await evaluate(
            cases,
            llm_for_case=lambda case_id: PerCallClient(
                batch,
                lambda request_id: build_guarded_llm(
                    settings,
                    database,
                    request_id=request_id,
                    merchant_id=None,
                    role=None,  # 离线评测只计入全局预算
                    purpose="AGENT",
                ),
                f"intent:{case_id}",
                max_output_tokens=settings.llm_max_output_tokens_per_call,
            ),
            index_text=index.text,
            today=TODAY,
            on_case=lambda row: append_evidence(dump, row),
        )
        append_evidence(dump, {"event": "REPORT", "complete": True, "report": report})
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await database.dispose()


if __name__ == "__main__":
    from app.core.runtime import configure_event_loop_policy

    parser = argparse.ArgumentParser(description="v1 意图识别准确率真实评测（需要 R3 费用授权）")
    parser.add_argument("--real", action="store_true", help="发起至多 400 次真实 DeepSeek 调用")
    parser.add_argument("--dump", type=Path, required=True, help="逐例结果 JSONL")
    parser.add_argument("--ledger", type=Path, required=True, help="本批次专用的 JSONL 账本")
    args = parser.parse_args()
    if not args.real:
        parser.error("仅支持显式 --real；Fake 验证请运行 tests/eval/test_intent_accuracy_fake.py")
    configure_event_loop_policy()  # Windows 上 psycopg 异步模式不支持 Proactor 循环
    asyncio.run(_run_real(args.dump, args.ledger))
