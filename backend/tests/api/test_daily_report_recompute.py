"""管理员日报重算的 HTTP 边界。每项断言针对一个可观察的运维约束。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models.merchant import Merchant
from app.models.operations import AuditLog
from app.services.report_service import DailyReportService
from tests.conftest import ADMIN_TOKEN, MERCHANT_ONE_AUTH, MERCHANT_ONE_ID

pytestmark = pytest.mark.asyncio

PATH = "/api/admin/reports/daily/recompute"


async def _daily_report(client: AsyncClient) -> dict[str, object]:
    response = await client.get("/api/reports/daily", headers=MERCHANT_ONE_AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def _payload(report_date: str, **overrides: object) -> dict[str, object]:
    return {
        "merchant_id": str(MERCHANT_ONE_ID),
        "report_date": report_date,
        "reason": "首次滚动后清除旧日报缓存",
        **overrides,
    }


async def test_recompute_replaces_unreviewed_daily_report_and_audits(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    before = await _daily_report(postgres_client)

    response = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload(str(before["report_date"])),
    )

    assert response.status_code == 200, response.text
    assert response.json()["report_date"] == before["report_date"]
    assert response.json()["answer_id"] != before["answer_id"]
    async with postgres_app.state.database.session() as session:
        logs = list(await session.scalars(select(AuditLog)))
    assert [(log.event_type, log.merchant_id, log.resource_id) for log in logs] == [
        ("DAILY_REPORT_RECOMPUTED", MERCHANT_ONE_ID, str(before["report_date"]))
    ]
    assert logs[0].event_metadata == {
        "reason": "首次滚动后清除旧日报缓存",
        "report_date": str(before["report_date"]),
    }


async def test_recompute_requires_admin_token(postgres_client: AsyncClient) -> None:
    before = await _daily_report(postgres_client)

    response = await postgres_client.post(PATH, json=_payload(str(before["report_date"])))

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


async def test_recompute_rejects_unknown_merchant(postgres_client: AsyncClient) -> None:
    before = await _daily_report(postgres_client)

    response = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload(
            str(before["report_date"]),
            merchant_id="00000000-0000-0000-0000-0000000000ff",
        ),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_recompute_rejects_non_demo_merchant(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> None:
    before = await _daily_report(postgres_client)
    non_demo_id = UUID("00000000-0000-0000-0000-0000000001ff")
    async with postgres_app.state.database.session() as session:
        session.add(
            Merchant(
                id=non_demo_id,
                merchant_code="borough-api-non-demo",
                display_name="非演示商家",
                is_demo=False,
            )
        )
        await session.commit()

    response = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload(str(before["report_date"]), merchant_id=str(non_demo_id)),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_recompute_rejects_invalid_date_and_blank_reason(
    postgres_client: AsyncClient,
) -> None:
    before = await _daily_report(postgres_client)
    report_date = date.fromisoformat(str(before["report_date"]))

    future = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload((report_date + timedelta(days=2)).isoformat()),
    )
    blank_reason = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload(report_date.isoformat(), reason="   "),
    )
    too_old = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload((report_date - timedelta(days=180)).isoformat()),
    )

    assert future.status_code == 422
    assert blank_reason.status_code == 422
    assert too_old.status_code == 422


async def test_recompute_rejects_daily_report_with_feedback(postgres_client: AsyncClient) -> None:
    before = await _daily_report(postgres_client)
    feedback = await postgres_client.post(
        f"/api/answers/{before['answer_id']}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True, "reaction": None},
    )
    assert feedback.status_code == 200, feedback.text

    response = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload(str(before["report_date"])),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DAILY_REPORT_FEEDBACK_CONFLICT"


async def test_concurrent_recompute_returns_in_progress_without_duplicate_rows(
    postgres_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = await _daily_report(postgres_client)
    started = asyncio.Event()
    release = asyncio.Event()
    original = DailyReportService._build_response

    async def slow_build(
        self: DailyReportService,
        merchant_id: UUID,
        report_date: date,
    ):
        started.set()
        await release.wait()
        return await original(self, merchant_id, report_date)

    monkeypatch.setattr(DailyReportService, "_build_response", slow_build)
    first = asyncio.create_task(
        postgres_client.post(
            PATH,
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json=_payload(str(before["report_date"])),
        )
    )
    await started.wait()
    second = await postgres_client.post(
        PATH,
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json=_payload(str(before["report_date"])),
    )
    release.set()
    first_response = await first

    assert first_response.status_code == 200, first_response.text
    assert second.status_code == 409
    assert second.json()["code"] == "REQUEST_IN_PROGRESS"
