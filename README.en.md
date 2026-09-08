<p align="right">
  <a href="README.md">简体中文</a> · <b>English</b>
</p>

# Borough Merchant AI Assistant

> A conversational Data Agent for e-commerce merchants: ask about your business data in plain language and get
> an answer that comes **with metric definitions, charts, actionable recommendations — and a pass from an independent reviewer**.

<p>
<img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.116-009688?logo=fastapi&logoColor=white">
<img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-orchestration-1C3C3C">
<img alt="Vue" src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vuedotjs&logoColor=white">
<img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white">
<img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white">
<img alt="Railway" src="https://img.shields.io/badge/Deploy-Railway-0B0D0E?logo=railway&logoColor=white">
</p>

A merchant types *"how has my return volume trended over the last 7 days?"* and the system resolves the merchant
identity → decides whether the question is even in scope → parses it into a structured intent → queries PostgreSQL
through **backend SQL templates** (the model never touches SQL) → produces a conclusion, a chart and at least two
evidence-backed recommendations → hands it to an independent reviewer → persists the answer and asynchronously
distils it into merchant memory. If any stage is unavailable the system **degrades visibly and says why on screen**,
rather than inventing a plausible-looking answer.

> The in-product UI copy and the design docs under `docs/` are written in Chinese; this README is the English
> counterpart of [`README.md`](README.md).

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [The Agent Pipeline](#the-agent-pipeline)
- [Security and Cost Controls](#security-and-cost-controls)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Testing and Quality Gates](#testing-and-quality-gates)
- [API Overview](#api-overview)
- [Deployment](#deployment)
- [Repository Layout](#repository-layout)
- [Documentation Index](#documentation-index)

---

## Overview

Borough Merchant AI Assistant is a conversational Data Agent for e-commerce merchants. A merchant asks in plain
language; the system turns that question into a controlled data query and answers with the metric's definition,
a chart, and concrete next steps.

It targets a handful of specific problems in day-to-day merchant analytics:

- Business data is spread across orders, refunds, products, coupons and support tickets, which makes any
  cross-domain question expensive to answer;
- Merchants don't know how a metric is computed, shouldn't have to touch database internals, and certainly
  shouldn't have to write SQL;
- A metric answer is usually just a number — no definition, no explanation of the trend, no "so what do I do next";
- Platform rules and metric definitions live scattered across documents and people's heads;
- Wiring an LLM straight to a database invites misread questions, invented fields, arithmetic errors and
  out-of-scope queries.

The stack is deliberately small: Python + TypeScript, with a single PostgreSQL database carrying every storage
responsibility — no separate analytical database, no extra data pipeline. Redis, async workers and object storage
get added when a real requirement demands them, not up front. Fewer moving parts means a far lower barrier to
understanding, developing, testing and deploying the thing.

`Borough` is a fictional e-commerce platform invented for this project. All demo merchants and business data are
**programmatically generated fiction** — no real merchant information is involved. Demo identity maps a token
allow-list directly onto three fictional merchants, switchable from the top bar, which is also how you verify
tenant isolation. No sign-up, no login.

## Screenshots

<img src="docs/images/01-assistant.png" alt="Borough Merchant AI Assistant main view">

<p align="center"><i>Main view: daily report and metric definition on the left, conversation and the 12-step quality trail in the middle, recommendations and suggested follow-ups on the right</i></p>

| Chat BI dashboard | Knowledge base admin |
| :---: | :---: |
| <img src="docs/images/04-ops-dashboard.png" alt="Chat BI dashboard"> | <img src="docs/images/03-knowledge-base.png" alt="Knowledge base admin"> |
| Six north-star metrics, daily trend and category drill-down; an insufficient sample reads "insufficient sample" rather than a fabricated 0% | Fixed three-root tree, four business sections, document editing, read-only memory |

<table>
<tr>
<td width="26%"><img src="docs/images/02-chart.png" alt="Metric chart panel"></td>
<td>

**Metric chart**

Fields may only come from dimension and metric columns registered on the backend — the model
cannot name arbitrary ones — and the selectable chart types come from the backend's `allowed_types`.
The summary shares its number formatting with the detail table, so floating-point summation noise
never reaches the user.

</td>
</tr>
<tr>
<td width="26%"><img src="docs/images/05-mobile.png" alt="Mobile layout"></td>
<td>

**Mobile**

On narrow screens the three columns collapse into a conversation-first single column.
Metric definitions, charts and recommendations unfold inline with the conversation,
and the composer stays pinned to the bottom.

</td>
</tr>
</table>

## Features

### Conversation and analysis

- **Six answer modes** — `METRIC` trends, `DETAIL` row-level data, `RULE` platform policy, `IDENTITY` merchant
  profile, `CHAT` small talk, `INVALID` out-of-scope refusal — routed by the structured intent;
- **Metrics**: GMV, order volume, return volume, refund amount, support-ticket volume and more, with trend,
  dimensional breakdown, period-over-period and year-over-year comparison;
- **Metric definitions**: both the business definition and the SQL definition (13 fields), resolved through a
  three-tier lookup (metric catalogue → knowledge base → model-generated). The source, and whether the definition
  was generated, are always visible to the user;
- **Detail queries and export**: orders, refunds, products, coupons and support tickets. CSV export goes through an
  HMAC-signed URL with a 15-minute TTL, a UTF-8 BOM, and formula-injection protection;
- **Charts**: line, bar and pie. Fields may only come from registered dimension and metric columns — the model
  cannot name arbitrary columns;
- **Recommendations**: at least two actionable suggestions, each backed by data;
- **Quality trail**: the UI shows all 12 real processing stages, the quality status
  (`PASSED` / `DEGRADED` / `FAILED` / `NOT_RUN`), the number of review attempts, and the reason for any degradation;
- **Feedback loop**: adopt / thumbs-up / thumbs-down, written idempotently; cross-merchant attempts return 403 and
  are audited.

### Platform capabilities

- **Daily business report**: yesterday's six metrics in `Asia/Shanghai` plus two deterministic recommendations,
  materialised idempotently under a `daily-report:{date}` key. No LLM involved at any point;
- **Merchant memory**: successful answers are asynchronously distilled from that merchant's history in the same
  category. Team knowledge takes priority and memory is only a fallback — memory **never** gets promoted back into
  the team knowledge base;
- **Suggested follow-ups**, ranked by the merchant's own most frequent historical questions in that category, with
  aggregation, ordering and `LIMIT` all pushed down into SQL. A failed statistics query is isolated by a savepoint
  and falls back to static suggestions without poisoning the main chat transaction;
- **Knowledge base admin**: token-gated, with a fixed three-root tree, four fixed business sections, document CRUD,
  `If-Match` optimistic locking, and 412 conflicts that preserve the user's input;
- **Chat BI dashboard**: north-star metrics — adoption rate, accuracy, average thinking time, question hit rate,
  answer failure rate — rolled up idempotently by day × merchant × category, with category drill-down and a
  re-computation job.

## Architecture

```mermaid
flowchart LR
    U["Merchant browser<br/>Vue 3 + Pinia + ECharts"]
    C["Caddy static hosting"]
    A["FastAPI<br/>auth / rate limit / cost guard"]
    G["LangGraph QA graph<br/>12 nodes"]
    L["DeepSeek<br/>OpenAI-compatible API"]
    Q["SafeQueryService<br/>allow-list + templated SQL"]
    K["Knowledge / metric catalogue / memory"]
    P[("PostgreSQL")]

    U --> C
    U -- "SSE / JSON" --> A
    A --> G
    G -- "structured intent, never SQL" --> L
    G --> K
    G --> Q
    Q --> P
    K --> P
    A --> P
```

Key decisions:

- **The frontend does not proxy the API.** Caddy only serves static assets; the browser talks to the backend's
  public origin directly. CORS therefore allows one exact origin, and a missing `VITE_API_BASE_URL` **fails loudly**
  instead of silently sending requests to the static server and collecting 404s;
- **Types flow one way**: `OpenAPI → api/generated.ts → api/adapters/*.ts → types/*.ts → store → components`.
  Components never consume generated types directly; adapters are the single conversion point and each one has a
  contract test — so a backend field change turns them red immediately;
- **ORM models and API schemas are separate.** An ORM object is never exposed as an external contract.

## The Agent Pipeline

```text
load_context → retrieve_knowledge_index → prefilter_question ─┬→ classify_intent → understand_intent
                                                              │  → validate_intent → retrieve_knowledge_detail
                                                              │  → query_data → compose_answer → quality_loop ─┐
                                                              │                                                ↓
                                                              └────────（zero-LLM refusal）────────→ suggest_questions → persist_answer
```

Two nodes worth calling out:

**`prefilter_question` — a zero-LLM scope gate.**
Before it existed, an obviously unrelated question like *"what's the difference between a CNN and an RNN?"* still
cost at least one real model call; there was no path that could refuse for free. It now runs dependency-free n-gram
tokenisation and scores the question against knowledge-document titles and paths, the metric catalogue's
`display_name` / `metric_code`, and the merchant's own memory. Below threshold, a conditional edge skips every
LLM-driven node outright. It deliberately **does not use a blocklist** — irrelevant vocabulary cannot be enumerated —
but an allow-list score that fails closed, with three fail-open cases: the corpus being entirely unavailable
(fresh deployment, empty knowledge base), greetings, and any conversation that already has prior turns. That last
one exists so a legitimate follow-up like *"and what about last month?"*, which contains no business vocabulary,
is not wrongly refused. In real-model acceptance testing, all three out-of-scope questions cost **zero LLM calls**.

**`quality_loop` — generate → deterministic local validation → independent reviewer → feed-back retry → fallback.**
Degradation reasons are classified as `UPSTREAM` / `VALIDATION` / `BUDGET`, and the attempt limit is injected via
`QUALITY_MAX_ATTEMPTS`. A controlled degradation only summarises facts from the current query, and **never reports a
total when the detail rows were truncated**.

## Security and Cost Controls

This is where most of the engineering effort went, and it is what separates an LLM demo from something you would
actually expose to the public internet.

| Risk | Design |
| --- | --- |
| Model emitting arbitrary SQL | The model may **only** emit a structured query intent validated by Pydantic. SQL is generated from backend templates: table and column names come from an allow-list, every value is bound, and date ranges and row caps are enforced server-side |
| Cross-tenant access | `merchant_id` is derived from the bearer token only and is **never** taken from the client. Every business query has the merchant scope forced in; cross-merchant access returns 403 and lands in `audit_logs` |
| Token bill blow-up | Three gates: per-request LLM call cap (worst-case path is 10, reconciled against how the two retry loops multiply), per-request token cap, and a global daily token budget breaker — on top of the zero-LLM prefilter above |
| Prompt injection / unauthorised reads | Knowledge and memory retrieval are merchant-scoped; logs are redacted and never record private fields or full result sets |
| Admin and merchant surfaces getting conflated | **Two independent credentials**: merchants use `Authorization: Bearer`, admins use `X-Admin-Token`, and the backend accepts only the latter on `/api/admin/*`. When `ADMIN_TOKEN` is unset the entire admin router **is not mounted** — a 404 rather than a 401, so the endpoint's existence isn't leaked |
| Read-only public demo | An optional `VIEWER_TOKEN` shares the admin header but the backend only lets GETs through: writes, memory compression and the ops status endpoint are always rejected. Setting it equal to `ADMIN_TOKEN` is refused at startup |
| Degradation disguised as a real answer | `analysis_sources` / `thinking_steps` / `quality_status` / `quality_notes` / `degraded` / `degraded_reason` are all part of the API contract and are rendered in the UI. A rule-based fallback **must never** be presented as model analysis |
| Leaked export links | Signed URLs: HMAC plus a 15-minute TTL. This is the only authenticated path that requires no request header |
| Forged proxy headers | Only the platform's injected forwarding headers are trusted (`TRUSTED_PROXY_HOPS`); local development trusts no client-supplied `X-Forwarded-For` at all |
| Secrets in source | All secrets come from environment variables / Railway Variables, and `.env.example` holds placeholders only. `secrets:check` recursively scans the built JS, CSS, HTML, JSON and source maps to block secret-shaped strings |

## Tech Stack

**Backend**　Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic · psycopg · LangGraph ·
structlog · pytest · Ruff · mypy (strict)

**Frontend**　Vue 3 · TypeScript · Vite · Pinia · Vue Router · ECharts · Zod · Vitest · Playwright · ESLint · Prettier

**Data and infrastructure**　PostgreSQL 16 · Docker · Caddy · Railway (frontend / backend / cron)

**Model**　DeepSeek (OpenAI-compatible chat completions), default `deepseek-v4-flash`

## Getting Started

### Prerequisites

Python 3.12, [uv](https://github.com/astral-sh/uv), Node.js 20+, Docker.

```powershell
git clone https://github.com/XuZiHan-010/shopping_assistant.git
cd shopping_assistant
```

### 1. Start PostgreSQL

```powershell
docker-compose -p borough up -d postgres   # listens on 127.0.0.1:55432
```

### 2. Start the backend

```powershell
cd backend
uv sync

$env:DATABASE_URL = 'postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test'
$env:FRONTEND_ORIGIN = 'http://localhost:5173'
$env:DEMO_MERCHANT_TOKENS = '{"merchant-100-token":"00000000-0000-0000-0000-000000000001","merchant-101-token":"00000000-0000-0000-0000-000000000002","merchant-102-token":"00000000-0000-0000-0000-000000000003"}'

uv run alembic upgrade head
uv run python -m app.run                   # http://127.0.0.1:8000
```

Verify with `GET /api/health` (touches neither the database nor the LLM) and `GET /api/ready` (runs only `SELECT 1`).

> **Note for Windows**: psycopg's async mode cannot run on the default `ProactorEventLoop`. Any new entry point must
> select the event loop explicitly (see `backend/app/core/runtime.py`), otherwise the symptom is `/api/ready`
> returning 503.

### 3. Seed the demo data

```powershell
# from the repository root
uv run --project backend python scripts/seed_demo_data.py --seed      # three fictional merchants

cd backend
# 180 days of business data. Day to day this is maintained incrementally by
# app.jobs.seed_demo_rolling; a full rebuild wipes history, hence the explicit flag.
uv run python -m scripts.seed_demo_analytics --force-full-rebuild

# Team business-knowledge documents; point --root at a directory of Markdown files
uv run python -m scripts.import_wiki --root <knowledge-directory>
```

> A full pytest run truncates `knowledge_documents` and the business tables, so re-run the last two commands
> afterwards.

### 4. Start the frontend

```powershell
cd frontend
npm ci
npm run dev                                # http://localhost:5173
```

The frontend locates the backend through `VITE_API_BASE_URL`. There is deliberately no same-origin `/api` fallback:
if the variable is missing, it errors out.

### 5. (Optional) Wire up a real model

With no `LLM_API_KEY` configured the system uses a deterministic fake client — the whole flow runs end to end and
costs nothing. To connect the real DeepSeek API:

```text
LLM_API_KEY=<deepseek-api-key>
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
LLM_ENABLED=true
```

The full list of environment variables is in [`.env.example`](.env.example), where each threshold is annotated with
why it holds its current value — for instance `LLM_MAX_OUTPUT_TOKENS_PER_CALL` sits at its ceiling of 8000 because a
reasoning model will otherwise spend a smaller allowance entirely on reasoning, return an empty body, and force the
whole chain to degrade.

## Testing and Quality Gates

Automated tests use **fake / deterministic LLMs exclusively and never incur model costs**.

```powershell
# backend
cd backend
uv run ruff check . ; uv run ruff format --check . ; uv run mypy app
uv run pytest                                     # integration tests self-skip without a real test database
$env:REQUIRE_INTEGRATION_DB = '1'; uv run pytest  # required in CI: an unreachable database now fails hard

# frontend
cd frontend
npm run lint ; npm run typecheck ; npm run test
npm run test:e2e            # Playwright (mocked API)
npm run codegen:check       # has generated.ts drifted from the OpenAPI spec?
npm run fixtures:check      # are the adapter contract fixtures stale?
npm run firstpaint:check    # keeps ECharts out of the first-paint static import chain
npm run secrets:check       # scans dist/ for secret-shaped strings
npm run mock:check          # keeps mock payloads out of production builds
```

Most recent recorded results: a full backend regression against a real PostgreSQL instance at
**1049 passed / 0 failed / 0 skipped** (2026-08-24); after the latest change, backend **941 passed**
(plus 212 skipped when the integration database is not running), frontend Vitest **353 passed**, E2E **29 passed**.

Three testing constraints that came out of things going wrong:

- **Integration tests must run against real PostgreSQL, not SQLite** — tenant isolation, migrations and seeding are
  all validated there;
- **`FakeLlmClient` masks an entire class of defect.** It returns pre-written valid JSON, which makes "does the
  prompt actually tell the model what to output?" completely invisible to the test suite. Any new or modified prompt
  therefore ships with a prompt contract test that **derives its expectations from the Pydantic model**;
- **All gates green does not mean the behaviour is right.** A stray `history=[]` survived for weeks behind 899
  passing tests. Any parameter that is supposed to carry a value but is being passed an empty one now needs a test
  that asserts on the *content* of the input, not merely that nothing threw.

## API Overview

The complete contract is exported from FastAPI to [`docs/api.md`](docs/api.md) and [`docs/api.json`](docs/api.json).

| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/chat` | SSE stream by default (`step` / `done` / `error`); `Accept: application/json` takes the synchronous path, and the `done` payload is byte-for-byte identical to it |
| `GET` | `/api/conversations`, `/api/conversations/{id}` | Conversation list and detail |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation |
| `POST` | `/api/answers/{id}/feedback` | Adopt / thumbs-up / thumbs-down (idempotent) |
| `GET` | `/api/exports/{id}` | Signed CSV download (the only authenticated path with no required header) |
| `GET` | `/api/metrics/{code}` | Metric definition (the path parameter is `metric_code`, not a display name) |
| `GET` | `/api/reports/daily` | Daily business report |
| `GET` | `/api/demo/merchants` | Demo merchant list (disabled in production by default) |
| `GET` | `/api/health`, `/api/ready` | Health check / readiness probe |
| `GET` `POST` `PUT` `DELETE` | `/api/admin/knowledge/*` | Knowledge tree, document CRUD, business domains, memory compression |
| `GET` `POST` | `/api/admin/analytics/chatbi/*` | Chat BI overview, category drill-down, roll-up refresh |
| `POST` | `/api/admin/reports/daily/recompute` | Recompute a given merchant's daily report |
| `GET` | `/api/admin/ops/status` | Remaining budget, rate-limit hits and degradation counts (never tokens, prompts or business data) |

## Deployment

Four kinds of service run on Railway: `frontend` (multi-stage Node build → `caddy:2-alpine`), `backend`, PostgreSQL,
and two standalone cron services (rolling demo-data seed, Chat BI daily roll-up). Configuration is checked in as
`frontend/railway.json`, `backend/railway.json`, `backend/railway.cron.json` and
`backend/railway.chatbi-cron.json`; the operations runbook is [`docs/deployment.md`](docs/deployment.md).

Settled constraints:

- **Codegen does not run at image build time.** Railway's frontend build context does not contain the repository
  root's `docs/`, so `src/api/generated.ts` is a generated artefact committed to the repo, kept fresh by
  `codegen:check`;
- `VITE_API_BASE_URL` is baked into the static bundle at build time and must be supplied by Railway Variables;
- Database migrations run in the release phase, not concurrently from every worker;
- Attachments never rely on the container's ephemeral disk.

## Repository Layout

```text
merchant_assistant/
├── backend/                    # FastAPI backend
│   ├── app/
│   │   ├── agent/              # LangGraph QA graph, state, prefilter gate, nodes
│   │   ├── api/routes/         # chat / conversations / metrics / exports / reports / admin ...
│   │   ├── services/           # safe_query · answer · review · quality_loop · memory · chatbi ...
│   │   ├── intent/             # structured intent models and allow-list validation
│   │   ├── repositories/       # data access (tenant isolation is enforced here)
│   │   ├── analytics/          # metric formulas and demo-data generation
│   │   ├── llm/                # DeepSeek client and cost guard
│   │   ├── jobs/               # rolling seed, Chat BI roll-up CLI
│   │   └── knowledge/ prompts/ models/ schemas/ core/ db/
│   ├── migrations/             # Alembic
│   └── tests/                  # unit / integration / api / agent
├── frontend/                   # Vue 3 frontend
│   ├── src/
│   │   ├── views/              # AssistantView · KnowledgeBaseView · OpsDashboardView
│   │   ├── components/         # chat / insights / knowledge / analytics / layout
│   │   ├── api/                # client · sse · generated.ts (never hand-edited) · adapters/
│   │   └── stores/ types/ composables/
│   └── e2e/                    # Playwright
├── docs/                       # PRD, frontend/backend plans, API export, deployment
├── scripts/                    # demo seeding, OpenAPI export, fixture export
└── plans/                      # implementation and remediation plans
```

## Documentation Index

All design documents are written in Chinese.

| Document | Contents |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Development rules, directory index and build order (the entry point for coding agents) |
| [`docs/PRD.md`](docs/PRD.md) | Product scope, user stories, architectural decisions, acceptance criteria |
| [`docs/project-progress.md`](docs/project-progress.md) | Current progress snapshot: phase, verification results, next steps, risks |
| [`docs/backend-development-plan.md`](docs/backend-development-plan.md) | Backend phases and the exact `ChatRequest` / `ChatResponse` / SSE contract |
| [`docs/frontend-development-plan.md`](docs/frontend-development-plan.md) | Frontend phases and definition of done |
| [`docs/api.md`](docs/api.md) | OpenAPI export (the final source of truth for API fields) |
| [`docs/deployment.md`](docs/deployment.md) | Railway deployment and operations runbook |

---

## Notes

- Demo merchants, business data and knowledge documents are all fictional and exist purely to demonstrate the product;
- This is a personal engineering project and is not affiliated with any real e-commerce platform.
