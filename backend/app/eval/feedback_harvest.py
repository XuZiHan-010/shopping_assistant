"""E6 线上反馈回流：把点踩与降级的回合整理成**候选清单**，交人工决定是否进评测集（PRD E6，Q30）。

三条边界：

1. **只产出候选清单，不写评测集**。输出目录落在 `app/eval/datasets/` 之内一律拒绝；
   是否采纳、改写成什么样的用例，由人决定。脚本也不把线上内容写进任何提示词。
2. **先脱敏、去重、归因**。候选里只有改写前的问题文本（已遮蔽联系方式、证件号、长数字与标识符）
   和归因字段（端、语言、回答模式、降级原因、质量状态、反馈原因），**没有**回答正文、商家或顾客标识、
   会话与对话 ID。遮蔽之后只剩个人信息的样本直接丢弃。
3. **调优集与最终测试集互斥**。两个集合按案例指纹（端 + 归一化后的问题文本）比对，
   同一个案例不能既用来调提示词又用来做最终验收。

读取线上库是跨商家的只读操作，属于运维行为：对生产库运行前须取得同意，输出文件按内部资料保管。

用法（在 `backend/` 下，`DATABASE_URL` 指向目标库）::

    uv run python -m app.eval.feedback_harvest --since 2026-10-01 --until 2026-10-08 \\
        --output ../.eval-feedback
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_config import JobSettings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.answer import Answer, Feedback
from app.models.conversation import Message

DATASETS_ROOT: Final = Path(__file__).resolve().parent / "datasets"
#: 最终测试集：进门禁与基线对照的用例。调优集：人工采纳后只用于调提示词的用例（目录可以不存在）。
SPLIT_DIRECTORIES: Final[Mapping[str, tuple[Path, ...]]] = {
    "final": (
        DATASETS_ROOT / "security",
        DATASETS_ROOT / "quality",
        DATASETS_ROOT / "quality" / "scenarios",
    ),
    "tuning": (DATASETS_ROOT / "tuning",),
}

Role = Literal["CUSTOMER", "MERCHANT"]
Signal = Literal["DISLIKE", "DEGRADED"]

_MAX_QUESTION_CHARS: Final = 500
_MASK: Final = "[已遮蔽]"
#: 顺序有意义：先遮蔽形态最明确的，再兜底遮蔽长数字（订单号、卡号、内部编号）。
_REDACTIONS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}"),
    re.compile(r"\d{17}[\dXx]"),
    re.compile(r"1[3-9]\d{9}"),
    re.compile(r"\d{9,}"),
)
_PUNCTUATION: Final = re.compile(r"[\s\W_]+", re.UNICODE)


def redact(text: str) -> str:
    """遮蔽联系方式、证件号、UUID 与 9 位以上的长数字；普通问题原样返回。"""

    cleaned = text
    for pattern in _REDACTIONS:
        cleaned = pattern.sub(_MASK, cleaned)
    return cleaned


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return _PUNCTUATION.sub("", folded)


def case_fingerprint(role: str, question: str) -> str:
    """案例指纹：端 + 归一化后的问题文本。空白、大小写、全半角与标点的差异不产生新指纹。"""

    return sha256(f"{role}\x1f{_normalize(question)}".encode()).hexdigest()


# ---- 线上样本 → 候选 -------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackSample:
    """一条点踩或降级的回合。只带归因需要的字段，没有任何主体标识。"""

    role: Role
    locale: str
    question: str
    signal: Signal
    answer_mode: str | None
    degraded_reason: str | None
    quality_status: str | None
    feedback_reason: str | None
    created_at: datetime


@dataclass
class Candidate:
    fingerprint: str
    role: Role
    locale: str
    question: str
    occurrences: int = 0
    signals: list[str] = field(default_factory=list)
    answer_modes: list[str] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    quality_statuses: list[str] = field(default_factory=list)
    feedback_reasons: list[str] = field(default_factory=list)
    first_seen: date | None = None
    last_seen: date | None = None
    #: 已有用例覆盖了同一个指纹：提醒审阅者不要重复收录。
    already_in_dataset: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "role": self.role,
            "locale": self.locale,
            "question": self.question,
            "occurrences": self.occurrences,
            "signals": self.signals,
            "answer_modes": self.answer_modes,
            "degraded_reasons": self.degraded_reasons,
            "quality_statuses": self.quality_statuses,
            "feedback_reasons": self.feedback_reasons,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "already_in_dataset": self.already_in_dataset,
        }


def _add(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)
        values.sort()


def build_candidates(
    samples: Iterable[FeedbackSample], *, known_fingerprints: frozenset[str]
) -> list[Candidate]:
    """脱敏 → 按指纹去重 → 汇总归因；按出现次数降序（同次数按指纹）返回。"""

    merged: dict[str, Candidate] = {}
    for sample in samples:
        question = redact(sample.question).strip()[:_MAX_QUESTION_CHARS]
        # 遮蔽后没有实质内容的样本没有复盘价值，也不该留下。
        if not _normalize(question.replace(_MASK, "")):
            continue
        fingerprint = case_fingerprint(sample.role, question)
        candidate = merged.get(fingerprint)
        if candidate is None:
            candidate = merged[fingerprint] = Candidate(
                fingerprint=fingerprint,
                role=sample.role,
                locale=sample.locale,
                question=question,
                already_in_dataset=fingerprint in known_fingerprints,
            )
        candidate.occurrences += 1
        _add(candidate.signals, sample.signal)
        _add(candidate.answer_modes, sample.answer_mode)
        _add(candidate.degraded_reasons, sample.degraded_reason)
        _add(candidate.quality_statuses, sample.quality_status)
        if sample.feedback_reason:
            _add(candidate.feedback_reasons, redact(sample.feedback_reason).strip())
        day = sample.created_at.astimezone(UTC).date()
        candidate.first_seen = min(candidate.first_seen or day, day)
        candidate.last_seen = max(candidate.last_seen or day, day)
    return sorted(merged.values(), key=lambda item: (-item.occurrences, item.fingerprint))


def write_candidates(candidates: Sequence[Candidate], *, output: Path) -> Path:
    """把候选清单写成 JSONL；目标落在评测集目录之内时拒绝，不创建任何文件。"""

    target = output.resolve()
    datasets = DATASETS_ROOT.resolve()
    if target == datasets or datasets in target.parents:
        raise ValueError("回流脚本不得写入评测集目录；候选清单须经人工审阅后手工收录")
    target.mkdir(parents=True, exist_ok=True)
    path = target / "feedback-candidates.jsonl"
    path.write_text(
        "".join(json.dumps(item.to_json(), ensure_ascii=False) + "\n" for item in candidates),
        encoding="utf-8",
    )
    return path


# ---- 评测集指纹与互斥 ------------------------------------------------------------------------


def _messages(node: object) -> Iterator[str]:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key == "message" and isinstance(value, str):
                yield value
            else:
                yield from _messages(value)
    elif isinstance(node, list):
        for item in node:
            yield from _messages(item)


def fingerprints_in(directory: Path) -> frozenset[str]:
    """目录下全部用例里每条用户消息的指纹；目录不存在视为空集。"""

    found: set[str] = set()
    if not directory.is_dir():
        return frozenset()
    for path in sorted(directory.glob("*.yaml")):
        cases = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for case in cases:
            if not isinstance(case, Mapping) or "role" not in case:
                continue
            for message in _messages(case.get("turns", [])):
                found.add(case_fingerprint(str(case["role"]), message))
    return frozenset(found)


def dataset_fingerprints(split: Literal["final", "tuning"]) -> frozenset[str]:
    found: set[str] = set()
    for directory in SPLIT_DIRECTORIES[split]:
        found |= fingerprints_in(directory)
    return frozenset(found)


def assert_disjoint(*, tuning: frozenset[str], final: frozenset[str]) -> None:
    overlap = tuning & final
    if overlap:
        raise ValueError(
            f"{len(overlap)} 个案例同时出现在调优集与最终测试集：{sorted(overlap)[:5]}"
        )


# ---- 读库 -----------------------------------------------------------------------------------


async def harvest_samples(
    session: AsyncSession, *, since: datetime, until: datetime, limit: int = 2000
) -> list[FeedbackSample]:
    """读取时间窗内被点踩或带降级标记的已完成回合。跨商家只读，不返回任何主体标识。"""

    if since.tzinfo is None or until.tzinfo is None or since >= until:
        raise ValueError("时间窗必须带时区且起点早于终点")
    if not 1 <= limit <= 10_000:
        raise ValueError("无效的样本上限")
    degraded = Answer.response_payload["degraded"].as_boolean().is_(True)
    rows = (
        await session.execute(
            select(Answer, Message.content, Feedback.reaction, Feedback.reason)
            .join(Message, Message.id == Answer.user_message_id)
            .outerjoin(Feedback, Feedback.answer_id == Answer.id)
            .where(
                Answer.processing_status == "SUCCEEDED",
                Answer.created_at >= since,
                Answer.created_at < until,
                or_(Feedback.reaction == "DISLIKE", degraded),
            )
            .order_by(Answer.created_at, Answer.id)
            .limit(limit)
        )
    ).all()
    samples: list[FeedbackSample] = []
    for answer, question, reaction, reason in rows:
        payload = answer.response_payload or {}
        role: Role = "CUSTOMER" if answer.surface == "SHOP" else "MERCHANT"
        common = {
            "role": role,
            "locale": answer.response_locale,
            "question": question,
            "answer_mode": payload.get("answer_mode"),
            "degraded_reason": payload.get("degraded_reason"),
            "quality_status": payload.get("quality_status"),
            "created_at": answer.created_at,
        }
        if reaction == "DISLIKE":
            samples.append(FeedbackSample(signal="DISLIKE", feedback_reason=reason, **common))
        if payload.get("degraded") is True:
            samples.append(FeedbackSample(signal="DEGRADED", feedback_reason=None, **common))
    return samples


async def _run(since: date, until: date, output: Path) -> Path:
    database = Database(JobSettings())
    try:
        async with database.session() as session:
            samples = await harvest_samples(
                session,
                since=datetime.combine(since, time(0), UTC),
                until=datetime.combine(until, time(0), UTC),
            )
    finally:
        await database.dispose()
    known = dataset_fingerprints("final") | dataset_fingerprints("tuning")
    return write_candidates(build_candidates(samples, known_fingerprints=known), output=output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把点踩与降级的回合整理成评测候选清单（不写评测集）"
    )
    parser.add_argument(
        "--since", type=date.fromisoformat, required=True, help="起始日期（UTC，含）"
    )
    parser.add_argument(
        "--until", type=date.fromisoformat, required=True, help="结束日期（UTC，不含）"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="候选清单输出目录，不得在评测集目录内"
    )
    args = parser.parse_args()
    configure_event_loop_policy()
    path = asyncio.run(_run(args.since, args.until, args.output))
    print(f"候选清单已写入 {path}；请人工审阅后再决定是否收录进评测集")


if __name__ == "__main__":
    main()
