"""E5 抽取评测；真实模式须经 R3 费用授权后手动运行。"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import yaml
from sqlalchemy.engine import make_url

from app.api.dependencies import build_guarded_llm
from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.llm.client import LlmBudget, LlmClient, LlmMessage
from app.memory.extractor import MemoryExtractor
from app.memory.filters import filter_candidate, filter_persisted

DATASET = Path(__file__).parent / "datasets/memory/n4_e5_extraction.yaml"


async def evaluate(
    cases: list[dict[str, object]], *, llm_for_case: Callable[[str], LlmClient],
    max_tokens: int = 4000,
) -> dict[str, object]:
    """逐条独立预算；只输出聚合与失败 ID，不记录用户文本或模型原文。"""
    correct = wrong = missed = 0
    failed_ids: list[str] = []
    for case in cases:
        case_id = str(case["id"])
        user = str(case["user"])
        expected = bool(case["expected"])
        messages = []
        if "assistant" in case:
            messages.append(LlmMessage(role="assistant", content=str(case["assistant"])))
        messages.append(LlmMessage(role="user", content=user))
        candidates = await MemoryExtractor().extract(
            messages, llm=llm_for_case(case_id),
            budget=LlmBudget(max_calls=1, max_tokens=max_tokens),
        )
        accepted = [
            candidate for candidate in candidates
            if not filter_candidate(candidate).rejected
            and not filter_persisted(candidate).rejected
        ]
        target = str(case["value"]).replace(" ", "")
        matches = any(
            (target in candidate.value.replace(" ", "")
             or candidate.value.replace(" ", "") in target)
            and len(candidate.value.strip()) >= 2
            for candidate in accepted
        )
        if expected and matches and len(accepted) == 1:
            correct += 1
        elif accepted:
            wrong += len(accepted)
            failed_ids.append(case_id)
        elif expected:
            missed += 1
            failed_ids.append(case_id)
    total = len(cases)
    return {
        "cases": total,
        "correct_writes": correct,
        "wrong_writes": wrong,
        "missed": missed,
        "precision": correct / (correct + wrong) if correct + wrong else 1.0,
        "wrong_write_rate": wrong / total if total else 0.0,
        "failed_case_ids": failed_ids,
        "note": "自动评分只用字面目标；近义事实与复杂纠正需人工复核。",
    }


async def _run_real() -> None:
    settings = Settings()
    url = make_url(settings.database_url)
    if url.host not in {"127.0.0.1", "localhost"} or not (url.database or "").endswith("_test"):
        raise ValueError("E5 真实评测只允许本地可丢弃 _test 数据库")
    if not settings.llm_api_key or settings.llm_model != "deepseek-flash":
        raise ValueError("E5 真实评测须配置 DeepSeek Key 和 deepseek-flash")
    cases = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    if len(cases) != 40:
        raise ValueError("E5 评测集数量已变化，需重新取得费用授权")
    database = Database(settings)
    try:
        report = await evaluate(
            cases,
            llm_for_case=lambda case_id: build_guarded_llm(
                settings, database, request_id=f"memory-e5:{case_id}",
                merchant_id=None, purpose="MEMORY",
            ),
            max_tokens=settings.memory_extraction_max_tokens,
        )
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="N4 E5 真实模型评测（需要 R3 费用授权）")
    parser.add_argument("--real", action="store_true", help="发起 40 次真实 DeepSeek 调用")
    args = parser.parse_args()
    if not args.real:
        parser.error("仅支持显式 --real；Fake 验证请运行 E5 pytest")
    configure_event_loop_policy()  # Windows 上 psycopg 异步模式不支持 Proactor 循环
    asyncio.run(_run_real())
