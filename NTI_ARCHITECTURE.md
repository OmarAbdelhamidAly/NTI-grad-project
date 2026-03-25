# 🏛️ Architecture Documentation

**DataAnalyst.AI — Autonomous Enterprise Data Analyst**

---

## Table of Contents

1. [Architectural Principles](#1-architectural-principles)
2. [System Overview](#2-system-overview)
3. [4-Layer Service Architecture](#3-4-layer-service-architecture)
4. [LangGraph Pipeline Deep-Dive](#4-langgraph-pipeline-deep-dive)
5. [Security Architecture](#5-security-architecture)
6. [Data Flow — Full Query Lifecycle](#6-data-flow--full-query-lifecycle)
7. [Database Schema](#7-database-schema)
8. [Infrastructure & Deployment](#8-infrastructure--deployment)
9. [Observability Stack](#9-observability-stack)
10. [Key Design Decisions](#10-key-design-decisions)

---

## 1. Architectural Principles

**Separation by concern, not by team.**
Each service owns one concept: the API Gateway owns HTTP concerns (auth, routing, validation), the Governance worker owns policy enforcement, the execution pillars own analysis. No service does two jobs.

**Celery queues as the API between layers.**
Services communicate only through named Celery queues over Redis. `api` → `governance` queue → `pillar.sql` queue. No direct HTTP calls between workers. A worker crash never blocks the API — the job stays in the queue until a healthy worker picks it up.

**Stateless workers, stateful checkpointing.**
Every Celery worker is ephemeral. LangGraph state is persisted to Redis via `AsyncRedisSaver`. A HITL-paused SQL job survives a worker restart, a pod eviction, or a full cluster reboot.

**Multi-tenant at the data layer, not the application layer.**
A single API deployment serves all tenants. Isolation is enforced by `tenant_id` on every database query — not by separate databases or deployments. Every query is scoped in a SQLAlchemy `where(Model.tenant_id == current_user.tenant_id)` clause. Tenant A cannot detect the existence of Tenant B's resources.

**Fail loudly in development, fail safely in production.**
The `Settings` validator crashes startup if `SECRET_KEY` or `AES_KEY` are at their default values when `ENV=production`. You cannot accidentally deploy with weak secrets.

**Observability is not optional.**
Every service emits structured logs via `structlog`. Prometheus metrics are scraped at `/metrics`. Grafana dashboards are provisioned automatically — no manual setup.

---

## 2. System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL WORLD                                   │
│                                                                          │
│  Browser / API client          Groq API (LLM)         Qdrant Cloud       │
│       │                            ▲                       ▲             │
└───────┼────────────────────────────┼───────────────────────┼─────────────┘
        │ HTTPS :8002                │ HTTPS                 │ :6333
┌───────▼────────────────────────────┼───────────────────────┼─────────────┐
│                  DOCKER COMPOSE NETWORK                     │            │
│                                    │                        │            │
│  ┌──────────────────────────────────────────────────────────┐            │
│  │  API GATEWAY  (services/api · :8002)                     │            │
│  │  FastAPI · Async SQLAlchemy · JWT · AES-256              │            │
│  └───────────────────────────┬──────────────────────────────┘            │
│                               │ Celery tasks                              │
│                        ┌──────▼──────┐                                   │
│                        │    REDIS    │ Broker + cache + JWT blacklist     │
│                        │             │ + LangGraph HITL checkpoints       │
│                        └──────┬──────┘                                   │
│           ┌───────────────────┼───────────────────┐                      │
│           ▼                   ▼                   ▼                      │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐  │
│  │  GOVERNANCE    │  │  WORKER-SQL    │  │  WORKER-CSV / JSON / PDF   │  │
│  │  (Layer 2)     │  │  (Layer 3)     │  │  (Layer 3)                 │  │
│  │  LangGraph:    │  │  LangGraph:    │  │  LangGraph pipelines       │  │
│  │  intake →      │  │  11-node SQL   │  │  per data type             │  │
│  │  guardrail     │  │  pipeline      │  │                            │  │
│  └────────────────┘  └────────────────┘  └────────────────────────────┘  │
│           │                   │                   │                      │
│           └───────────────────┼───────────────────┘                      │
│                               │ export queue                              │
│                        ┌──────▼──────┐                                   │
│                        │  EXPORTER   │ (Layer 4) PDF/XLSX/JSON           │
│                        └─────────────┘                                   │
│                                                                           │
│  ┌─────────────────┐  ┌──────────────────────────────────────────────┐   │
│  │   PostgreSQL    │  │              Shared Volume ./tenants/        │   │
│  │   :5433         │  │  Uploaded files, exported reports            │   │
│  │   Metadata DB   │  └──────────────────────────────────────────────┘   │
│  └─────────────────┘                                                      │
│                                                                           │
│  ┌─────────────────┐  ┌─────────────────┐                                │
│  │   Prometheus    │  │     Grafana     │ Observability stack            │
│  │   :9090         │  │     :3000       │                                │
│  └─────────────────┘  └─────────────────┘                                │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 4-Layer Service Architecture

### Layer 1 — API Gateway (`services/api`)

The only public-facing service. Handles HTTP, auth, file storage, and Celery dispatch. Never executes analysis logic.

**Routing table:**

| Endpoint Group | Responsibility |
|---|---|
| `/auth/*` | JWT issuance, refresh rotation, Redis JTI revocation |
| `/data-sources/*` | File upload, schema profiling, SQL credential encryption, auto-analysis dispatch |
| `/analysis/*` | Job submission, status polling, HITL approval, result retrieval |
| `/knowledge/*` | PDF ingestion → Qdrant ColPali indexing |
| `/policies/*` | Admin guardrail rule management |
| `/metrics/*` | Job analytics, latency stats, tenant usage |
| `/reports/*` | Async export dispatch + signed download URLs |

**Key infrastructure modules:**

```
infrastructure/
├── config.py           Pydantic Settings — validates env vars on startup
├── security.py         JWT access (30min) + refresh (7 days) + bcrypt
├── sql_guard.py        3-layer SQL injection prevention
├── middleware.py        CORS · rate limiting (slowapi) · security headers
├── token_blacklist.py  Redis-backed JTI revocation set
└── adapters/
    ├── encryption.py   AES-256-GCM — encrypt/decrypt SQL connection strings
    ├── qdrant.py       Async Qdrant client — multi-vector upsert + search
    └── storage.py      Tenant-scoped file path resolution
```

---

### Layer 2 — Governance (`services/governance`)

Dedicated Celery worker on the `governance` queue. Every job passes through here before reaching any execution pillar.

**LangGraph graph:**
```
START → [intake_agent] → check_intake → [guardrail_agent] → END
                               │
                               └── clarification_needed → END
```

**Intake Agent responsibilities:**
- Classify question intent: `trend | comparison | ranking | correlation | anomaly`
- Extract named entities (table names, column names, date ranges)
- Detect ambiguous or underspecified questions
- Assign complexity index (1–5) based on entity count and join requirements

**Guardrail Agent responsibilities:**
- Load active policies for the tenant from PostgreSQL
- LLM semantic check: does this question violate any policy?
- PII detection: would the answer expose sensitive columns?
- If violation: set job to `error` status with a human-readable explanation

---

### Layer 3 — Execution Pillars

Four workers, each independently scalable:

```
worker-sql   → queues: pillar.sql, pillar.sqlite, pillar.postgresql
worker-csv   → queue:  pillar.csv
worker-json  → queue:  pillar.json
worker-pdf   → queue:  pillar.pdf
```

Each worker is a separate Docker container with its own `requirements.txt`. The SQL worker can scale to 10 replicas without affecting CSV or PDF processing.

---

### Layer 4 — Exporter (`services/exporter`)

Async worker on the `export` queue. Receives completed `AnalysisResult` objects and renders them to:
- **PDF** — formatted report with charts as static images
- **XLSX** — data snapshot in Sheet 1, recommendations in Sheet 2
- **JSON** — raw result envelope for downstream consumption

Output files are written to `tenant_uploads/{tenant_id}/exports/` and served via signed download URLs through the API Gateway.

---

## 4. LangGraph Pipeline Deep-Dive

### SQL Pipeline — 11 Nodes

The most complex pipeline. Handles schema discovery, HITL approval, self-healing on zero results, hybrid PDF fusion, and quality verification.

```
START
  │
  ▼
[data_discovery]
  │  Tools: sql_schema_discovery
  │  • Connects to the database (decrypts AES-256 credentials from state)
  │  • Profiles up to 5,000 rows per table
  │  • Extracts: column names, types, PKs, FKs, sample values, low-cardinality enums
  │  • Generates Mermaid ERD for complex schemas
  │  • schema_selector compresses to relevant tables for the question
  │
  ▼
[analysis_generator]
  │  ReAct agent with tools: sql_schema_discovery, run_sql_query (dry-run)
  │  Retrieves golden SQL examples from insight_memory (similar past questions)
  │  Generates: ANSI SELECT query + execution plan annotation
  │  sql_validator: syntax check before routing
  │
  ▼
route_after_generator
  ├── auto_analysis=True → skip HITL → [execution]
  └── user job          → [human_approval]
                              │  INTERRUPT fires (interrupt_before=["human_approval"])
                              │  Full graph state serialized to Redis (AsyncRedisSaver)
                              │  Job status: awaiting_approval
                              │  Generated SQL surfaced to admin in UI
                              │
                              │  POST /analysis/{id}/approve
                              │  State updated: {approval_granted: True}
                              │  Graph resumed from checkpoint
                              ▼
                         [execution]
                              │  Tools: run_sql_query (live mode, ≤1,000 rows)
                              │  Captures: row_count, column_names, data_snapshot
                              │
                         route_after_execution
                          ├── row_count=0 → [backtrack]
                          │      │  Compares SQL literals against low_cardinality_values
                          │      │  Detects case mismatches (e.g. "q4" vs "Q4")
                          │      │  Injects correction hint into state
                          │      │  retry_count += 1 (max 3)
                          │      └──► [analysis_generator]
                          │
                          └── success → [hybrid_fusion]
                                            │  If kb_id present: Qdrant multi-vector search
                                            │  Retrieves PDF context related to SQL result
                                            │  Merges into state for insight generation
                                            ▼
                                      [visualization]
                                            │  Selects chart type based on intent + data shape
                                            │  Generates Plotly JSON spec (bar/line/scatter/pie)
                                            ▼
                                       [insight]
                                            │  3–5 sentence executive summary
                                            │  Grounds claims in actual row values
                                            │  References PDF context if hybrid_fusion ran
                                            ▼
                                       [verifier]
                                            │  Quality gate: does the insight match the data?
                                            │  If mismatch: regenerates insight (once)
                                            │  Prevents hallucinated insights
                                            ▼
                                   [recommendation]
                                            │  3 specific, actionable next steps
                                            │  Tied to the question intent and data findings
                                            ▼
                                  [memory_persistence]
                                            │  Saves {question → SQL} to insight_memory table
                                            │  Used as golden examples in future analysis_generator
                                            ▼
                                  [output_assembler]
                                            │  Builds final JSON: charts + insight + recommendations
                                            │  + data_snapshot + thinking_steps
                                            │  Writes AnalysisResult to PostgreSQL
                                            │  Updates job status to "done"
                                            ▼
                                           END
```

---

### CSV Pipeline — 7 Nodes

Simpler pipeline — no HITL needed (user-uploaded files have no live DB credentials at risk).

```
START
  │
  ▼
[data_discovery]
  │  Tools: profile_dataframe
  │  • Pandas dtype inference
  │  • Null ratio per column
  │  • Unique value counts
  │  • Outlier density (IQR method)
  │  • Computes data_quality_score = f(null_ratio, type_consistency, outlier_density)
  │
  ▼
needs_cleaning? (data_quality_score < 0.9)
  ├── YES → [data_cleaning]
  │      │  Tools: clean_dataframe
  │      │  • Null imputation (median for numeric, mode for categorical)
  │      │  • Type coercion (string dates → datetime64)
  │      │  • Outlier flagging (adds _outlier boolean column)
  │      └──► [analysis]
  └── NO  →    [analysis]
                   │  Tools: compute_trend, compute_ranking, compute_correlation
                   │  Selects tool based on classified intent
                   │  Executes Pandas operations, returns summary stats + data
                   ▼
             [visualization]
                   │  Generates Plotly chart spec appropriate to the analysis type
                   ▼
              [insight]        → Executive summary grounded in computed statistics
                   ▼
          [recommendation]     → 3 next steps
                   ▼
         [output_assembler]    → Final JSON → PostgreSQL → job status "done"
                   ▼
                  END
```

---

### Governance Pipeline — 2 Nodes

```
START → [intake_agent] → check_intake → [guardrail_agent] → END
                               │
                               └── clarification_needed → END
```

The bypass path: `auto_analysis` system user skips governance. Background analyses triggered on upload don't need guardrail checks because the question is system-generated and policy-safe by construction.

---

## 5. Security Architecture

### JWT Authentication Flow

```
POST /auth/register or /auth/login
  └── Returns: access_token (30min) + refresh_token (7 days)
               Both tokens contain a JTI (JWT ID) — a unique UUID per token

Protected Request
  └── Authorization: Bearer {access_token}
      └── Verify signature → decode claims → check JTI not in Redis blacklist

Access Token Expired
  └── POST /auth/refresh {refresh_token}
      └── Verify refresh_token signature + expiry + JTI not in blacklist
          └── DELETE old JTI from Redis (rotation — old token dead immediately)
              └── Issue new access_token + new refresh_token

POST /auth/logout {refresh_token}
  └── ADD refresh_token JTI to Redis blacklist (SET with TTL = remaining token lifetime)
      └── Token is permanently dead — even if someone captured it, it's worthless
```

### SQL Guard — 3 Layers in Sequence

```python
# services/api/app/infrastructure/sql_guard.py

def validate_sql(query: str) -> None:
    stripped = query.strip().upper()

    # Layer 1: Allowlist — must start with SELECT or WITH (CTEs)
    if not stripped.startswith(("SELECT", "WITH")):
        raise ValueError("Only SELECT queries are permitted")

    # Layer 2: Blocklist — reject dangerous DML/DDL keywords anywhere
    DANGEROUS_PATTERN = r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|TRUNCATE|CREATE|EXEC|EXECUTE|GRANT|REVOKE|MERGE|CALL|XP_|SP_)\b"
    match = re.search(DANGEROUS_PATTERN, query, re.IGNORECASE)
    if match:
        raise ValueError(f"Forbidden SQL keyword: {match.group()}")

    # Layer 3: LLM Guardrail (runs in governance worker, not here)
    # Semantic policy enforcement: catches "comp" when policy says "never expose salary"
```

Layer 3 runs in the Governance worker, not in the API Gateway. This allows the semantic check to be tenant-aware (loads active policies from PostgreSQL) without coupling the API layer to LLM calls.

### AES-256-GCM Credential Encryption

```python
# services/api/app/infrastructure/adapters/encryption.py

def encrypt_json(data: dict, key: bytes) -> str:
    """Encrypt a dict to a base64 string using AES-256-GCM."""
    plaintext = json.dumps(data).encode()
    nonce = os.urandom(12)         # 96-bit random nonce
    cipher = AESGCM(key)
    ciphertext = cipher.encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ciphertext).decode()

def decrypt_json(encrypted: str, key: bytes) -> dict:
    """Decrypt a base64 string back to a dict."""
    raw = base64.b64decode(encrypted.encode())
    nonce, ciphertext = raw[:12], raw[12:]
    cipher = AESGCM(key)
    plaintext = cipher.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode())
```

The `AES_KEY` env var is the only key material. It never enters the database. Loss of the key = permanent loss of all encrypted SQL credentials by design (no recovery path — this is the intended security property).

Decrypted credentials are injected into `AnalysisState` in memory and passed directly to the database connection. They are never written to disk, logged, or returned in API responses.

### Rate Limiting Implementation

```python
# services/api/app/infrastructure/middleware.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/auth/register")
@limiter.limit("3/minute")
async def register(...): ...

@router.post("/auth/login")
@limiter.limit("5/minute")
async def login(...): ...
```

Production note: behind a load balancer, configure `X-Forwarded-For` trust to ensure limits are per end-user IP, not per load balancer IP.

---

## 6. Data Flow — Full Query Lifecycle

```
User types: "What are the top 5 products by revenue in Q4?"
  │
  │  POST /api/v1/analysis/query { source_id, question, kb_id }
  ▼
API Gateway
  1. Verify JWT → extract user_id, tenant_id, role
  2. Verify data_source.tenant_id == user.tenant_id
  3. INSERT AnalysisJob(status="pending") → commit
  4. governance_task.apply_async(args=[job_id], queue="governance")
  5. Return { job_id, status="pending" } ← client gets this immediately

Redis receives task
  │
  ▼
Governance Worker
  6. Fetch job + data source from PostgreSQL
  7. Decrypt config_encrypted → connection_string (in memory only)
  8. intake_agent → intent="ranking", entities=["products","revenue","Q4"]
  9. guardrail_agent → load tenant policies → no violations
  10. pillar_task.apply_async(args=[job_id], queue="pillar.sql")

SQL Worker
  11. Build LangGraph graph with AsyncRedisSaver checkpointer
  12. [data_discovery] → schema: tables=sales,products; low_cardinality: quarter=["Q1","Q2","Q3","Q4"]
  13. [analysis_generator] →
      SELECT p.name, SUM(s.revenue) AS total
      FROM sales s JOIN products p ON s.product_id = p.id
      WHERE s.quarter = 'Q4'
      GROUP BY p.name ORDER BY total DESC LIMIT 5
  14. route_after_generator → user job → [human_approval] INTERRUPT
  15. State serialized to Redis. Job status → "awaiting_approval"
  16. Worker exits cleanly.

Client polls GET /analysis/{job_id}
  ← { status: "awaiting_approval", generated_sql: "SELECT p.name..." }

Admin reviews SQL in UI. Clicks "Approve".
  │
  │  POST /api/v1/analysis/{job_id}/approve
  ▼
API Gateway
  17. Verify admin role
  18. Update job status → "running"
  19. Patch LangGraph state in Redis: { approval_granted: true }
  20. pillar_task.apply_async(args=[job_id], queue="pillar.sql")

SQL Worker resumes from Redis checkpoint
  21. [execution] → runs SELECT → 5 rows, row_count=5
  22. [hybrid_fusion] → kb_id=null → skip Qdrant
  23. [visualization] → Plotly bar chart: products vs revenue
  24. [insight] → "Product A led Q4 with $2.3M, 28% of quarterly total..."
  25. [verifier] → insight references row values ✓
  26. [recommendation] → ["Prioritize Product A inventory...", ...]
  27. [memory_persistence] → save question+SQL to insight_memory
  28. [output_assembler] → build AnalysisResult JSON
  29. INSERT AnalysisResult → UPDATE job status → "done"

Client polls GET /analysis/{job_id} ← { status: "done" }
Client fetches GET /analysis/{job_id}/result
  ← { charts, insight_report, recommendations, data_snapshot }
```

Total time (typical): 8–18 seconds from query submission to result, excluding HITL pause.

---

## 7. Database Schema

**Entity Relationship:**

```
tenants ──< users
        ──< data_sources ──< analysis_jobs ──── analysis_results (1:1)
        ──< knowledge_bases
        ──< policies

analysis_jobs >── knowledge_bases (optional FK for hybrid PDF fusion)
analysis_jobs >── users (FK: user_id)
```

**Key design decisions:**

`config_encrypted TEXT` — credentials stored as a single encrypted blob. Encryption boundary is clean: all credential fields encrypted together, or none.

`thinking_steps JSON` — every LangGraph node output captured per job. Powers the "Reasoning" panel in the UI (audit trail + user trust).

`auto_analysis_json JSON` — 5 pre-generated analyses computed on upload. Displayed instantly on first open. First-impression latency matters for adoption.

`low_cardinality_values` (in `schema_json`) — sampled enum values per column, used by zero-row reflection to detect case mismatches without re-querying the database.

---

## 8. Infrastructure & Deployment

### Docker Compose — 12 Services

```yaml
# docker-compose.yml
services:
  postgres:      # PostgreSQL 16 — metadata database
  redis:         # Redis Stack — broker + cache + JWT blacklist + HITL checkpoints
  qdrant:        # Qdrant — vector database for PDF ColPali RAG
  api:           # FastAPI gateway :8002 + static SPA
  governance:    # Celery worker — governance queue
  worker-sql:    # Celery worker — pillar.sql queue
  worker-csv:    # Celery worker — pillar.csv queue
  worker-json:   # Celery worker — pillar.json queue
  worker-pdf:    # Celery worker — pillar.pdf queue
  exporter:      # Celery worker — export queue
  prometheus:    # Metrics collection :9090
  grafana:       # Dashboards :3000
```

All workers share `tenant_uploads` volume for file access. Redis is the only inter-service communication channel.

### Kubernetes — Production

Production adds:
- **HPA:** analysis workers auto-scale based on Celery queue depth (custom metric via Prometheus adapter)
- **PVC:** PostgreSQL and Qdrant data persistence across pod restarts
- **Ingress:** TLS termination + path routing
- **Namespace:** all resources in `analyst-ai` namespace
- **Secrets:** Kubernetes Secrets for `GROQ_API_KEY`, `SECRET_KEY`, `AES_KEY` (never in ConfigMap)

### Self-Healing Database Migration

```python
# services/api/app/main.py — lifespan context manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        # Step 1: Create all tables if they don't exist (idempotent)
        await conn.run_sync(Base.metadata.create_all)

        # Step 2: Add new columns to existing tables (idempotent)
        await conn.execute(text(
            "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS generated_sql TEXT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS thinking_steps JSON NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS auto_analysis_status VARCHAR(10) NULL"
        ))
    yield
```

Adding a new column requires only deploying new code — no migration script, no downtime, no rollback risk.

---

## 9. Observability Stack

### Prometheus

Scrapes metrics from the API Gateway at `/metrics` (Prometheus format via `prometheus-fastapi-instrumentator`):

```
analyst_api_requests_total{method, endpoint, status_code}
analyst_api_request_duration_seconds{method, endpoint}
analyst_jobs_total{status, intent, source_type}
analyst_jobs_duration_seconds{pipeline, node}
analyst_queue_depth{queue_name}
```

### Grafana

Pre-provisioned dashboards (no manual setup):

| Dashboard | Key Panels |
|---|---|
| **Platform Overview** | Active jobs, error rate, p50/p95/p99 latency, queue depths |
| **Pipeline Performance** | Per-node latency breakdown (SQL pipeline: 11 nodes) |
| **Tenant Analytics** | Jobs per tenant, data source distribution, intent breakdown |
| **Security** | Rate limit hits, auth failures, JWT revocations |

Access: `http://localhost:3000` — admin/admin (change in production).

### Structured Logging

All services emit JSON logs via `structlog`:

```json
{
  "timestamp": "2025-03-20T09:05:12.334Z",
  "level": "info",
  "service": "worker-sql",
  "tenant_id": "7c9e6679-...",
  "job_id": "job-uuid",
  "node": "execution",
  "row_count": 5,
  "duration_ms": 423
}
```

---

## 10. Key Design Decisions

### Why Celery queues between layers instead of HTTP?

HTTP between microservices creates tight coupling — if governance is down, analysis submissions fail immediately. Celery queues decouple producers from consumers: the API accepts jobs even when workers are restarting. Workers scale independently by adjusting `--concurrency`. Dead-letter queues catch and retry failed tasks without any code changes.

### Why one database for all tenants?

Multi-database tenancy (one DB per tenant) scales to thousands of tenants but requires a connection pool of thousands of connections, per-tenant migration management, and complex orchestration. Single-database with `tenant_id` scoping scales to hundreds of tenants with standard pooling and a single migration run. The isolation guarantee is equivalent — every query is WHERE-scoped. The only risk is an accidentally-omitted `tenant_id` filter, which is why all queries go through a central `get_current_user` dependency that enforces the scope.

### Why Redis checkpointer for HITL?

A Celery task cannot be "paused" — it must terminate and resume. LangGraph's `AsyncRedisSaver` serializes the full graph state to Redis when `interrupt_before=["human_approval"]` fires. On resume (POST /approve), the graph is reconstructed from the checkpoint and continues from exactly where it paused. This makes HITL durable across worker restarts, pod evictions, and cluster reboots.

### Why AES-256-GCM instead of a secrets manager?

A secrets manager (AWS Secrets Manager, HashiCorp Vault) is the right answer at scale. AES-256-GCM in the database is a defensible interim choice: production-grade encryption, zero external dependencies, simple to audit. The migration path is clean — replace `encrypt_json/decrypt_json` with secrets manager SDK calls.

### Why ColPali multi-vector for PDF RAG?

Traditional PDF RAG chunks text and embeds it. ColPali embeds PDF pages as image patches — preserving visual layout, tables, charts, and diagrams that text extraction destroys. For enterprise documents (financial reports, technical manuals), layout carries as much meaning as text. Multi-vector indexing in Qdrant stores both text embeddings and image patch embeddings per page, enabling queries that find information from charts with no adjacent text labels.

### Why Groq (Llama) instead of GPT-4?

Groq's inference hardware delivers sub-second token generation for Llama-3.1-8B — critical for an interactive analysis tool where users are waiting. The 8B model handles SQL generation, insight writing, and policy checking adequately for the task complexity. The 70B model is available as a config override for higher-stakes production deployments. The LLM provider is abstracted behind LangChain, making a future swap (OpenAI, Anthropic, local Ollama) a one-line config change.
