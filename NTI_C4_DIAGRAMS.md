# C4 Architecture Diagrams

**DataAnalyst.AI — Autonomous Enterprise Data Analyst**

> C4 Model: four levels of zoom — Context → Container → Component → Code.  
> Each diagram narrows scope. Start at Level 1 for the big picture.

---

## Level 1 — System Context

*Who uses the system, and what external systems does it interact with?*

```mermaid
graph TB
    Admin["👨‍💼 Admin User
    Connects data sources, approves
    SQL queries, sets guardrail policies,
    manages tenant users"]

    Viewer["👤 Analyst / Viewer
    Asks natural-language questions,
    views charts & insights,
    exports reports"]

    DevOps["👨‍💻 DevOps Engineer
    Deploys, monitors, and
    scales the platform"]

    System["🤖 DataAnalyst.AI
    Autonomous multi-tenant SaaS platform.
    Turns raw data into executive insights
    via multi-agent LangGraph pipelines.
    Supports CSV, SQL, JSON, and PDF."]

    Groq["☁️ Groq API
    LLM inference
    Llama-3.1-8B + 3.3-70B"]

    UserDB["🗄️ User's Database
    PostgreSQL / MySQL
    Enterprise data source"]

    Qdrant["🔍 Qdrant
    Vector database
    (optional cloud mode)"]

    Admin  -->|"HTTPS — manage, approve, configure"| System
    Viewer -->|"HTTPS — query, view, export"| System
    DevOps -->|"Docker / K8s / Prometheus"| System
    System -->|"LLM completions (HTTPS)"| Groq
    System -->|"Read-only SELECT queries"| UserDB
    System -->|"Vector upsert + search"| Qdrant

    style System fill:#1F3864,color:#fff,stroke:#2E5B8A
    style Groq   fill:#2E5B8A,color:#fff,stroke:#4472C4
    style UserDB fill:#2E5B8A,color:#fff,stroke:#4472C4
    style Qdrant fill:#2E5B8A,color:#fff,stroke:#4472C4
    style Admin  fill:#D5E8F0,color:#1F3864,stroke:#2E5B8A
    style Viewer fill:#D5E8F0,color:#1F3864,stroke:#2E5B8A
    style DevOps fill:#D5E8F0,color:#1F3864,stroke:#2E5B8A
```

---

## Level 2 — Container Diagram

*What are the deployable units, and how do they communicate?*

```mermaid
graph TB
    User["👤 User / Admin"]

    subgraph Docker ["🐳 Docker Compose Network"]
        UI["🖥️ Glassmorphism SPA
        Vanilla JS + Plotly.js
        Served from api/app/static/"]

        ReactUI["⚛️ React + TypeScript SPA
        Vite · Component-based UI
        Plotly.js charts · frontend/"]

        API["🔀 API Gateway
        FastAPI · asyncpg · :8002
        JWT auth · AES-256 encryption
        Rate limiting · Security headers"]

        subgraph Workers ["⚙️ Celery Workers"]
            Gov["🛡️ Governance
            queue: governance
            intake + guardrail agents"]

            SQL["🗃️ worker-sql
            queue: pillar.sql/.sqlite/.postgresql
            11-node LangGraph pipeline"]

            CSV["📊 worker-csv
            queue: pillar.csv
            7-node LangGraph pipeline"]

            Other["📄 worker-json · worker-pdf
            exporter
            pillar.json · pillar.pdf · export"]
        end

        subgraph Storage ["💾 Storage Layer"]
            PG["PostgreSQL :5433
            Tenants · Users · Jobs
            Results · Policies
            Insight Memory"]

            Redis["Redis :6379
            Celery broker
            JWT blacklist
            LangGraph checkpoints (HITL)"]

            QdrantLocal["Qdrant :6333
            PDF vector store
            ColPali multi-vector"]

            Vol["Shared Volume
            Uploaded CSV/PDF files
            Exported PDF/XLSX reports"]
        end

        subgraph Observability ["📈 Observability"]
            Prom["Prometheus :9090
            Metrics collection"]
            Graf["Grafana :3000
            Pre-provisioned dashboards"]
        end
    end

    Groq["☁️ Groq API"]

    User    -->|"HTTPS"| UI
    User    -->|"HTTPS"| ReactUI
    UI      -->|"fetch REST"| API
    ReactUI -->|"fetch REST"| API
    API     -->|"Celery task dispatch"| Redis
    Redis   -->|"task pickup"| Gov
    Gov     -->|"Celery task dispatch"| Redis
    Redis   -->|"task pickup"| SQL
    Redis   -->|"task pickup"| CSV
    Redis   -->|"task pickup"| Other
    API     -->|"asyncpg SQL"| PG
    SQL     -->|"asyncpg SQL"| PG
    CSV     -->|"asyncpg SQL"| PG
    SQL     -->|"LangGraph state (HITL)"| Redis
    SQL     -->|"vector search"| QdrantLocal
    Other   -->|"vector upsert"| QdrantLocal
    API     -->|"LLM calls"| Groq
    Gov     -->|"LLM calls"| Groq
    SQL     -->|"LLM calls"| Groq
    CSV     -->|"LLM calls"| Groq
    API     -->|"file I/O"| Vol
    Other   -->|"file I/O"| Vol
    API     -->|"expose /metrics"| Prom
    Prom    -->|"data source"| Graf

    style API fill:#1F6B4E,color:#fff
    style Redis fill:#DC382D,color:#fff
    style PG fill:#336791,color:#fff
    style QdrantLocal fill:#4F46E5,color:#fff
```

---

## Level 3 — Component Diagram: API Gateway

*What are the major components inside the API Gateway container?*

```mermaid
graph LR
    Client["Browser / API Client"]

    subgraph API ["services/api — FastAPI :8002"]
        MW["Middleware Stack
        CORS · Rate Limit (slowapi)
        Security Headers · structlog"]

        subgraph Routers ["Routers"]
            AuthR["auth.py
            register · login
            refresh · logout"]

            DSR["data_sources.py
            upload · connect
            list · delete
            auto-analysis"]

            AnalR["analysis.py
            query · status
            approve · reject
            result"]

            KnowR["knowledge.py
            upload PDF
            list · delete"]

            PolR["policies.py
            create · list
            update · delete"]

            MetR["metrics.py
            summary · jobs"]

            RepR["reports.py
            export · status
            download"]
        end

        subgraph Infra ["Infrastructure"]
            Sec["security.py
            JWT issue/verify
            bcrypt · JTI blacklist"]

            Guard["sql_guard.py
            Layer 1: SELECT-only
            Layer 2: keyword regex"]

            Enc["encryption.py
            AES-256-GCM
            encrypt/decrypt creds"]

            QdrantA["qdrant.py
            multi-vector upsert
            similarity search"]

            StorA["storage.py
            tenant-scoped paths
            file read/write"]
        end

        subgraph UC ["Use Cases"]
            Pipeline["run_pipeline.py
            Celery dispatch
            governance → pillar"]

            AutoA["auto_analysis.py
            5 pre-generated insights
            on data source upload"]

            Export["export.py
            Celery dispatch
            exporter queue"]
        end

        Static["static/
        Glassmorphism SPA
        HTML + CSS + JS"]
    end

    PG["PostgreSQL"]
    Redis["Redis"]

    Client --> MW --> Routers
    AuthR --> Sec
    AuthR --> PG
    DSR --> Enc
    DSR --> StorA
    DSR --> AutoA
    AnalR --> Guard
    AnalR --> Pipeline
    AnalR --> PG
    KnowR --> QdrantA
    RepR --> Export
    Pipeline --> Redis
    AutoA --> Redis
    Export --> Redis
    Sec --> Redis

    style MW fill:#FF6B35,color:#fff
    style Guard fill:#E74C3C,color:#fff
    style Enc fill:#8E44AD,color:#fff
```

---

## Level 3 — Component Diagram: SQL Worker

*What are the major components inside the SQL analysis worker?*

```mermaid
graph TD
    Celery["Celery Task Entry
    queue: pillar.sql"]

    subgraph SQLWorker ["services/worker-sql — LangGraph Pipeline"]
        WF["workflow.py
        LangGraph StateGraph
        AsyncRedisSaver checkpointer"]

        subgraph Agents ["Agents (11 nodes)"]
            DD["data_discovery
            Schema profiling
            low-cardinality sampling
            ERD generation"]

            AG["analysis_generator
            ReAct agent
            golden SQL retrieval
            ANSI SELECT generation"]

            HA["human_approval
            INTERRUPT node
            state serialized to Redis
            waits for admin POST /approve"]

            EX["execution
            Live SQL run (≤1,000 rows)
            row_count capture"]

            BK["backtrack
            Zero-row reflection
            Case mismatch detection
            Retry hint injection"]

            HF["hybrid_fusion
            Qdrant multi-vector search
            PDF context enrichment"]

            VZ["visualization
            Plotly JSON spec
            bar/line/scatter/pie"]

            IN["insight
            3–5 sentence summary
            grounded in row values"]

            VR["verifier
            Quality gate
            insight vs data check"]

            RC["recommendation
            3 action items
            intent-aware"]

            MP["memory_persistence
            golden SQL save
            insight_memory table"]
        end

        subgraph Tools ["Tools"]
            RunSQL["run_sql_query
            dry-run + live mode
            row count + snapshot"]

            SchDisc["sql_schema_discovery
            table profiling
            sample value extraction"]
        end

        subgraph Utils ["Utils"]
            GS["golden_sql
            retrieve similar
            past question→SQL pairs"]

            IM["insight_memory
            save/retrieve
            embeddings for similarity"]

            SM["schema_mapper
            column type normalization
            FK/PK detection"]

            SS["schema_selector
            compress schema to
            relevant tables only"]

            SV["sql_validator
            syntax pre-check
            before LLM routing"]
        end

        OA["output_assembler
        Final JSON build
        PostgreSQL write
        job status → done"]
    end

    Redis["Redis
    HITL checkpoint storage"]

    Groq["Groq API
    LLM inference"]

    PG["PostgreSQL
    AnalysisResult write"]

    Celery --> WF
    WF --> DD --> AG
    AG --> HA -->|"resume on approve"| EX
    AG -->|"auto_analysis"| EX
    EX -->|"row_count=0"| BK --> AG
    EX -->|"success"| HF --> VZ --> IN --> VR --> RC --> MP --> OA
    WF <-->|"state checkpoint"| Redis
    AG --> Groq
    IN --> Groq
    VR --> Groq
    RC --> Groq
    RunSQL -.-> EX
    SchDisc -.-> DD
    GS -.-> AG
    IM -.-> MP
    OA --> PG

    style HA fill:#FF6B35,color:#fff
    style BK fill:#E74C3C,color:#fff
    style VR fill:#27AE60,color:#fff
```

---

## Level 3 — Component Diagram: Governance Worker

*What are the components inside the Governance worker?*

```mermaid
graph LR
    Celery["Celery Task
    queue: governance"]

    subgraph GovWorker ["services/governance — LangGraph Pipeline"]
        WF["workflow.py
        2-node LangGraph StateGraph"]

        subgraph Agents ["Agents"]
            IA["intake_agent
            Intent classification:
            trend | comparison | ranking
            correlation | anomaly
            Entity extraction
            Ambiguity detection
            Complexity index (1–5)"]

            GA["guardrail_agent
            Load tenant active policies
            LLM semantic policy check
            PII column detection
            Violation → error status"]
        end

        Router["check_intake
        needs_clarification?
        → ask user to rephrase
        OR route to guardrail"]
    end

    PillarQ["Redis
    → pillar.sql / csv / json / pdf
    Celery task dispatch"]

    Groq["Groq API"]
    PG["PostgreSQL
    Tenant policies
    Job status update"]

    Celery --> WF
    WF --> IA --> Router
    Router -->|"clear"| GA --> PillarQ
    Router -->|"ambiguous"| PG
    IA --> Groq
    GA --> Groq
    GA --> PG

    style GA fill:#E74C3C,color:#fff
    style Router fill:#FF6B35,color:#fff
```

---

## Level 4 — Code Diagram: HITL Sequence

*How does Human-in-the-Loop approval work at the code level?*

```mermaid
sequenceDiagram
    participant Client
    participant API as API Gateway
    participant Redis
    participant SQLWorker as SQL Worker (LangGraph)
    participant Admin

    Client->>API: POST /analysis/query {question}
    API->>Redis: Dispatch governance_task
    Redis->>SQLWorker: Pick up task (eventually routed to SQL worker)
    SQLWorker->>SQLWorker: data_discovery → analysis_generator
    Note over SQLWorker: Generates SQL query
    SQLWorker->>Redis: Serialize full graph state (AsyncRedisSaver)
    Note over Redis: State key: checkpoint:{job_id}
    SQLWorker->>SQLWorker: INTERRUPT fires at human_approval node
    SQLWorker-->>API: Update job: status=awaiting_approval, generated_sql=...
    SQLWorker->>SQLWorker: Task exits cleanly

    Client->>API: GET /analysis/{job_id}
    API-->>Client: { status: "awaiting_approval", generated_sql: "SELECT..." }

    Admin->>API: POST /analysis/{job_id}/approve
    API->>Redis: Patch state: { approval_granted: true }
    API->>Redis: Dispatch pillar_task (resume)
    Redis->>SQLWorker: Pick up task

    SQLWorker->>Redis: Load state from checkpoint
    Note over SQLWorker: Graph resumes from human_approval node
    SQLWorker->>SQLWorker: execution → hybrid_fusion → visualization → insight → ...
    SQLWorker-->>API: Update job: status=done, write AnalysisResult

    Client->>API: GET /analysis/{job_id}/result
    API-->>Client: { charts, insight, recommendations }
```

---

## Level 4 — Code Diagram: Zero-Row Reflection

*How does the agent heal itself when a SQL query returns no results?*

```mermaid
sequenceDiagram
    participant Gen as analysis_generator
    participant Exec as execution
    participant Router as route_after_execution
    participant Back as backtrack
    participant State as LangGraph State

    Gen->>State: Write generated_sql = "SELECT ... WHERE quarter = 'q4'"
    Gen->>Exec: Route → execution
    Exec->>Exec: Run SQL against live DB
    Exec->>State: Write row_count = 0, reflection_context = null

    Exec->>Router: route_after_execution()
    Router->>State: Read row_count = 0
    Note over Router: row_count = 0 → reflection path
    Router->>State: Extract SQL literals: ["q4"]
    Router->>State: Compare against schema low_cardinality_values: quarter=["Q1","Q2","Q3","Q4"]
    Router->>State: Write reflection_context = "Case mismatch: 'q4' should be 'Q4'"
    Router->>Back: Route → backtrack

    Back->>State: Read reflection_context
    Back->>State: Write hint = "User used lowercase 'q4'; correct value is 'Q4'. Retry with exact case."
    Back->>State: Increment retry_count (now 1 of 3)
    Back->>Gen: Route → analysis_generator (retry)

    Gen->>Gen: Incorporate hint from state
    Gen->>State: Write generated_sql = "SELECT ... WHERE quarter = 'Q4'"
    Gen->>Exec: Route → execution
    Exec->>Exec: Run SQL against live DB
    Exec->>State: Write row_count = 5 ✓
    Exec->>Router: route_after_execution()
    Router->>Router: row_count > 0 → success path
    Router->>Router: Route → hybrid_fusion
```

---

## Architecture Decision Records (ADR)

| Decision | Choice | Rejected Alternatives | Rationale |
|---|---|---|---|
| Inter-service communication | Celery + Redis queues | Direct HTTP, gRPC | Decoupling — API works even when workers are restarting |
| HITL state persistence | Redis (AsyncRedisSaver) | PostgreSQL, in-memory | Survives worker restart; Redis is already in the stack |
| LLM provider | Groq (Llama) | OpenAI GPT-4, Claude | Sub-second inference latency; cost; LangChain abstraction enables easy swap |
| PDF embedding strategy | ColPali multi-vector | Text-only chunking | Preserves visual layout, tables, and charts; no text extraction required |
| Credential encryption | AES-256-GCM in DB | AWS Secrets Manager | Zero external dependencies; clear migration path to secrets manager |
| Tenant isolation | Shared DB + tenant_id | One DB per tenant | Simpler ops at NTI-project scale; equivalent isolation guarantee |
| Frontend | Vanilla JS SPA + React/TS | Angular, Vue | Vanilla for zero-build-step demo; React for production component reuse |
| Observability | Prometheus + Grafana | Datadog, New Relic | Self-hosted; zero cost; provisioned automatically |
