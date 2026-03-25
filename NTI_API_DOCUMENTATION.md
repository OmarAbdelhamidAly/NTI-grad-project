# 📡 API Documentation

**DataAnalyst.AI — Autonomous Enterprise Data Analyst**  
Base URL: `http://localhost:8002/api/v1`

All endpoints accept and return `application/json` unless noted.  
Protected endpoints require `Authorization: Bearer {access_token}`.

> **Interactive docs (Swagger UI):** `http://localhost:8002/docs` — available in `development` mode only. Hidden in production (`ENV=production`).

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Users](#2-users)
3. [Data Sources](#3-data-sources)
4. [Analysis](#4-analysis)
5. [Knowledge Bases](#5-knowledge-bases)
6. [Policies](#6-policies)
7. [Reports & Export](#7-reports--export)
8. [Metrics](#8-metrics)
9. [Health](#9-health)
10. [Error Responses](#10-error-responses)
11. [Role-Based Access](#11-role-based-access)
12. [Rate Limits Reference](#12-rate-limits-reference)

---

## 1. Authentication

### POST /auth/register

Create a new tenant and its first admin user in a single step.

**Rate limit:** 3 requests / minute per IP

**Request:**
```json
{
  "tenant_name": "Acme Corp",
  "email": "admin@acme.com",
  "password": "SecurePassword123!"
}
```

**Response `201`:**
```json
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "token_type": "bearer",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "admin@acme.com",
    "role": "admin",
    "tenant_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "created_at": "2025-03-16T10:00:00Z"
  }
}
```

**Errors:** `400` — Email already registered | `422` — Validation error

---

### POST /auth/login

Authenticate and receive JWT token pair.

**Rate limit:** 5 requests / minute per IP

**Request:**
```json
{
  "email": "admin@acme.com",
  "password": "SecurePassword123!"
}
```

**Response `200`:** Same structure as `/register`.

**Errors:** `401` — Invalid credentials

---

### POST /auth/refresh

Exchange a refresh token for a new token pair. The old refresh token is immediately revoked (rotation prevents token reuse attacks).

**Request:**
```json
{
  "refresh_token": "eyJhbGci..."
}
```

**Response `200`:** New `access_token` + `refresh_token`.

**Errors:** `401` — Expired, invalid, or already-revoked refresh token

---

### POST /auth/logout

**Protected.** Revoke the current refresh token. JTI is added to Redis blacklist — token is dead immediately, before natural expiry.

**Request:**
```json
{
  "refresh_token": "eyJhbGci..."
}
```

**Response `200`:**
```json
{ "message": "Logged out successfully" }
```

---

## 2. Users

### GET /users/me

**Protected.** Return the authenticated user's profile.

**Response `200`:**
```json
{
  "id": "550e8400-...",
  "email": "admin@acme.com",
  "role": "admin",
  "tenant_id": "7c9e6679-...",
  "created_at": "2025-03-16T10:00:00Z",
  "last_login": "2025-03-20T08:30:00Z"
}
```

---

### POST /users/invite

**Protected · Admin only.** Invite a viewer user to the tenant. Creates the user and returns credentials.

**Request:**
```json
{
  "email": "analyst@acme.com",
  "role": "viewer"
}
```

**Response `201`:**
```json
{
  "id": "...",
  "email": "analyst@acme.com",
  "role": "viewer",
  "tenant_id": "..."
}
```

---

### GET /users

**Protected · Admin only.** List all users in the tenant.

**Response `200`:** Array of user objects.

---

## 3. Data Sources

### POST /data-sources/upload

**Protected.** Upload a CSV, XLSX, or SQLite file. Triggers automatic schema profiling and background auto-analysis (5 pre-generated insights).

**Request:** `multipart/form-data`
- `file` — The data file
- `name` — Human-readable display name
- `domain_type` (optional) — `"sales" | "hr" | "finance" | "inventory" | "customer"`

**Response `201`:**
```json
{
  "id": "ds-uuid",
  "name": "Q4 Sales Data",
  "type": "csv",
  "domain_type": "sales",
  "schema_json": {
    "columns": ["product", "revenue", "quarter"],
    "dtypes": {"product": "object", "revenue": "float64", "quarter": "object"},
    "row_count": 12450,
    "sample_values": {"quarter": ["Q1", "Q2", "Q3", "Q4"]}
  },
  "auto_analysis_status": "pending",
  "created_at": "2025-03-20T09:00:00Z"
}
```

---

### POST /data-sources/connect

**Protected · Admin only.** Connect a live SQL database. Credentials are encrypted with AES-256-GCM before storage — the plaintext connection string is never persisted.

**Request:**
```json
{
  "name": "Production CRM",
  "db_type": "postgresql",
  "host": "db.acme.com",
  "port": 5432,
  "database": "crm_prod",
  "username": "readonly_user",
  "password": "...",
  "domain_type": "customer"
}
```

**Response `201`:** Data source object (credentials not returned).

---

### GET /data-sources

**Protected.** List all data sources for the authenticated tenant.

**Response `200`:** Array of data source objects.

---

### GET /data-sources/{id}

**Protected.** Retrieve a single data source including schema and auto-analysis status.

---

### GET /data-sources/{id}/auto-analysis

**Protected.** Retrieve the 5 pre-generated analyses computed on upload. Returns immediately if `auto_analysis_status == "done"`, otherwise returns current status.

**Response `200`:**
```json
{
  "status": "done",
  "analyses": [
    {
      "question": "What is the revenue trend over the last 4 quarters?",
      "insight": "Revenue grew 23% from Q1 to Q4, with Q3 showing the strongest single-quarter jump at +11%.",
      "chart": { /* Plotly spec */ },
      "recommendations": ["Investigate Q3 drivers...", "..."]
    }
  ]
}
```

---

### DELETE /data-sources/{id}

**Protected · Admin only.** Delete a data source and all associated jobs, results, and uploaded files.

---

## 4. Analysis

### POST /analysis/query

**Protected.** Submit a natural-language analysis question. Returns immediately with a `job_id` — use polling or the status endpoint to track progress.

**Request:**
```json
{
  "source_id": "ds-uuid",
  "question": "What are the top 5 products by revenue in Q4?",
  "kb_id": "kb-uuid"
}
```

- `kb_id` (optional) — Link a knowledge base for PDF hybrid fusion with SQL results

**Response `202`:**
```json
{
  "job_id": "job-uuid",
  "status": "pending",
  "message": "Analysis queued. Poll /analysis/{job_id} for updates."
}
```

---

### GET /analysis/{job_id}

**Protected.** Poll job status. For SQL jobs awaiting HITL approval, returns the generated SQL for admin review.

**Response `200` — in progress:**
```json
{
  "id": "job-uuid",
  "status": "running",
  "intent": "ranking",
  "complexity_index": 3,
  "thinking_steps": [
    {"node": "data_discovery", "output": "Found 12 tables, selected: sales, products"},
    {"node": "analysis_generator", "output": "Generated SQL targeting sales.revenue + products.name"}
  ]
}
```

**Response `200` — awaiting admin approval:**
```json
{
  "id": "job-uuid",
  "status": "awaiting_approval",
  "generated_sql": "SELECT p.name, SUM(s.revenue) AS total FROM sales s JOIN products p ON s.product_id = p.id WHERE s.quarter = 'Q4' GROUP BY p.name ORDER BY total DESC LIMIT 5",
  "message": "Admin approval required before SQL execution."
}
```

**Response `200` — completed:**
```json
{
  "id": "job-uuid",
  "status": "done",
  "completed_at": "2025-03-20T09:05:22Z"
}
```

---

### POST /analysis/{job_id}/approve

**Protected · Admin only.** Approve a HITL-paused SQL job. Resumes LangGraph execution from the Redis checkpoint.

**Response `200`:**
```json
{ "message": "Job approved and resumed." }
```

**Errors:** `403` — Viewer role | `404` — Job not found | `409` — Job not in awaiting_approval state

---

### POST /analysis/{job_id}/reject

**Protected · Admin only.** Reject a HITL-paused SQL job with an optional reason.

**Request:**
```json
{ "reason": "Query touches restricted compensation columns." }
```

---

### GET /analysis/{job_id}/result

**Protected.** Retrieve the full analysis result for a completed job.

**Response `200`:**
```json
{
  "job_id": "job-uuid",
  "charts": [
    {
      "type": "bar",
      "data": { /* Plotly data */ },
      "layout": { "title": "Top 5 Products by Q4 Revenue", "xaxis": {...}, "yaxis": {...} }
    }
  ],
  "insight_report": "Product A led Q4 with $2.3M in revenue, representing 28% of total quarterly sales. Products B and C showed strong momentum with 15% and 12% quarter-over-quarter growth respectively.",
  "recommendations": [
    "Prioritize Product A inventory for Q1 — demand signals suggest continued growth.",
    "Investigate Product D's 8% Q4 decline relative to Q3 performance.",
    "Run a cohort analysis on new customers acquired via Product C promotions."
  ],
  "data_snapshot": [
    {"name": "Product A", "total": 2300000},
    {"name": "Product B", "total": 1850000}
  ]
}
```

---

### GET /analysis

**Protected.** List all analysis jobs for the authenticated tenant. Supports filtering by status and date range.

**Query parameters:**
- `status` — Filter by status (`pending | running | done | error | awaiting_approval`)
- `source_id` — Filter by data source
- `limit` — Max results (default: 50)
- `offset` — Pagination offset

---

## 5. Knowledge Bases

### POST /knowledge

**Protected · Admin only.** Create a knowledge base and upload a PDF document. Triggers ColPali multi-vector indexing in Qdrant (text embeddings + image patch embeddings per page).

**Request:** `multipart/form-data`
- `file` — PDF document
- `name` — Knowledge base name
- `description` — Optional description

**Response `201`:**
```json
{
  "id": "kb-uuid",
  "name": "Product Catalog 2025",
  "description": "Official product specifications and pricing",
  "created_at": "..."
}
```

---

### GET /knowledge

**Protected.** List all knowledge bases for the tenant.

---

### DELETE /knowledge/{id}

**Protected · Admin only.** Delete a knowledge base and remove all associated Qdrant vectors.

---

## 6. Policies

Policies are natural-language guardrail rules enforced by the LLM Guardrail Agent before any SQL query executes.

**Example policies:**
- `"Never expose columns containing 'salary', 'compensation', or 'pay' in query results"`
- `"Reject any query that would return individual employee records"`
- `"Do not allow analysis of the users or auth_tokens tables"`

### POST /policies

**Protected · Admin only.**

**Request:**
```json
{
  "name": "PII Protection",
  "rule": "Never return columns containing personal identifiable information such as SSN, passport number, or date of birth.",
  "is_active": true
}
```

**Response `201`:** Policy object.

---

### GET /policies

**Protected.** List all policies for the tenant (active and inactive).

---

### PATCH /policies/{id}

**Protected · Admin only.** Update a policy rule or toggle `is_active`.

---

### DELETE /policies/{id}

**Protected · Admin only.**

---

## 7. Reports & Export

### POST /reports/{job_id}/export

**Protected.** Trigger async export of a completed analysis result. Returns a `report_id` for polling.

**Request:**
```json
{
  "format": "pdf"
}
```

- `format` — `"pdf" | "xlsx" | "json"`

**Response `202`:**
```json
{
  "report_id": "report-uuid",
  "status": "pending"
}
```

---

### GET /reports/{report_id}

**Protected.** Poll export status and retrieve download URL when ready.

**Response `200` — ready:**
```json
{
  "report_id": "report-uuid",
  "status": "done",
  "download_url": "/reports/report-uuid/download",
  "expires_at": "2025-03-20T10:00:00Z"
}
```

---

### GET /reports/{report_id}/download

**Protected.** Stream the generated report file. Returns `Content-Disposition: attachment` with appropriate MIME type.

---

## 8. Metrics

### GET /metrics/summary

**Protected · Admin only.** Tenant-level analytics: job counts by status, average latency, error rate, data source breakdown.

**Response `200`:**
```json
{
  "total_jobs": 847,
  "jobs_by_status": {
    "done": 801,
    "error": 23,
    "awaiting_approval": 8,
    "running": 15
  },
  "avg_completion_seconds": 14.3,
  "data_sources_count": 12,
  "top_intents": {
    "trend": 312,
    "ranking": 198,
    "comparison": 187,
    "correlation": 95,
    "anomaly": 55
  }
}
```

---

### GET /metrics/jobs

**Protected · Admin only.** Paginated job analytics with latency breakdown by pipeline node.

---

## 9. Health

### GET /health

No authentication required. Returns system health and service connectivity.

**Response `200`:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "services": {
    "database": "ok",
    "redis": "ok",
    "qdrant": "ok"
  },
  "timestamp": "2025-03-20T09:00:00Z"
}
```

**Response `503`:** If any critical service is unreachable.

---

## 10. Error Responses

All errors follow a consistent envelope:

```json
{
  "detail": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE",
  "timestamp": "2025-03-20T09:00:00Z"
}
```

| HTTP Code | Meaning |
|---|---|
| `400` | Bad request — validation or business logic error |
| `401` | Unauthenticated — missing or invalid JWT |
| `403` | Forbidden — authenticated but insufficient role |
| `404` | Resource not found (always tenant-scoped — cannot detect other tenants' resources) |
| `409` | Conflict — e.g. approving a job not in `awaiting_approval` state |
| `413` | Payload too large — file exceeds `MAX_UPLOAD_SIZE_MB` |
| `422` | Unprocessable entity — Pydantic validation failure |
| `429` | Rate limit exceeded |
| `503` | Service unavailable — upstream dependency down |

---

## 11. Role-Based Access

| Endpoint Group | `admin` | `viewer` |
|---|---|---|
| Register / login / refresh / logout | ✅ | ✅ |
| GET /users/me | ✅ | ✅ |
| POST /users/invite | ✅ | ❌ |
| POST /data-sources/upload | ✅ | ✅ |
| POST /data-sources/connect | ✅ | ❌ |
| DELETE /data-sources/{id} | ✅ | ❌ |
| POST /analysis/query | ✅ | ✅ |
| GET /analysis / GET /analysis/{id} | ✅ | ✅ |
| POST /analysis/{id}/approve | ✅ | ❌ |
| POST /analysis/{id}/reject | ✅ | ❌ |
| POST /knowledge | ✅ | ❌ |
| POST /policies | ✅ | ❌ |
| GET /metrics/summary | ✅ | ❌ |
| POST /reports/{id}/export | ✅ | ✅ |

---

## 12. Rate Limits Reference

| Endpoint | Limit | Enforcement |
|---|---|---|
| `POST /auth/register` | 3 / minute | Per IP |
| `POST /auth/login` | 5 / minute | Per IP |
| All other endpoints | 200 / minute | Per IP |

Rate limit headers are returned on every response:
```
X-RateLimit-Limit: 200
X-RateLimit-Remaining: 187
X-RateLimit-Reset: 1711024860
```

When exceeded, returns `429 Too Many Requests` with a `Retry-After` header.
