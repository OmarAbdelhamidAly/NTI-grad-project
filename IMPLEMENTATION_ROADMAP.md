# Master Implementation Roadmap
**Sources**: DS-STAR (2509.21825) · LLM-as-Data-Analyst Survey (2509.23988) · Unified Product Master Plan

---

## PART A: Enhancements to Existing Pipelines
*Modifications to code that already exists in `modules/sql`, `modules/csv`, and `modules/shared`.*

### Priority 1 — Modify `insight_agent.py` (Hybrid Insight Fusion) ⚡ 2 lines of code
- **What**: Inject KB (PDF) retrieval output into the Insight Agent's prompt alongside the SQL/CSV data.
- **Current state**: `insight_agent` only reads from `state["analysis_results"]` (SQL/CSV rows).
- **Gap**: KB context is used to *write SQL*, but not to *explain the results*.
- **Change**: Add `kb_context = await get_kb_context(...)` and include it in the `INSIGHT_PROMPT`.
- **Effect**: *"Sales dropped 23% (SQL) — internal logistics report (PDF) cites a warehouse flood on Mar 5th."*

---

### Priority 2 — Modify `sql_schema_discovery.py` (Content Retrieval) ⚡ ~10 lines
- **What**: Before generating SQL, auto-query `SELECT DISTINCT col LIMIT 10` for enum-like columns and inject into the prompt.
- **Current state**: Schema shows column names and types, but not actual values.
- **Gap**: LLM guesses `WHERE status = 'cancelled'` when the real value is `'CANCELLED'`.
- **Change**: After schema discovery, run quick DISTINCT queries on low-cardinality columns and add them to `schema_summary`.
- **Effect**: Reduces zero-row results by ~40% on filter-heavy queries.

---

### Priority 3 — Add `verifier_node` in `workflow.py` (Answer Sufficiency Judge) ⚡ 1 new node
- **What**: After `execution` node, add an LLM judge that evaluates: *"Does this result actually answer the user's strategic question?"*
- **Current state**: `execution` → `visualization` with no quality gate.
- **Gap**: SQL can return data that is technically correct but misses the user's intent (e.g., returns totals when growth rate was asked).
- **Change**: Add `verifier_node` in LangGraph. If `insufficient`, loops back to `analysis_generator`.
- **Effect**: Self-corrects logical gaps, not just syntax errors.

---

### Priority 4 — Enhance `analysis_agent.py` (Context-Aware Debugger) ⚡ ~5 lines
- **What**: When retrying after an error, include the full `data_description` (column names, dtypes, sample values) alongside the traceback.
- **Current state**: Error hint only passes the raw error string: `state['error']`.
- **Gap**: LLM doesn't know *why* the column name was wrong — it needs to see the actual schema.
- **Change**: Add `data_context` from `schema_summary` to the retry prompt in addition to the error message.
- **Effect**: Correct recovery on first retry instead of 2-3 failed retries.

---

### Priority 5 — Enhance `workflow.py` (Backtracking Router) ⚡ modify 1 conditional edge
- **What**: When a retry is needed, instead of patching the existing SQL, clear the generated SQL entirely and force a fresh generation pass.
- **Current state**: `should_retry` sends back to `analysis_generator` with the error as a hint, allowing the LLM to "patch" its own broken code.
- **Gap**: Patching complex wrong SQL often makes it worse (overly convoluted fixes).
- **Change**: On retry, add `"generated_sql": None` to state so the generator starts clean.
- **Effect**: Cleaner regeneration, not incremental patching of broken logic.

---

### Priority 6 — Enhance KB Ingestion (Execution-Based File Analyzer) ⚡ new ingestion step
- **What**: When a file is uploaded to the Knowledge Base, auto-run a Python script that captures its metadata (row count, column names, date ranges, data types) and saves it as a "data card" in Qdrant alongside the text chunks.
- **Current state**: Files are chunked and embedded as plain text only.
- **Gap**: Agents have no structured understanding of what each KB file *contains*.
- **Change**: Add a pre-ingestion step in `knowledge_router` that generates and embeds a structured data card.
- **Effect**: Agents can retrieve "what files do I have?" as a structured lookup before planning.

---
---

## PART B: New Pipeline Solutions
*Brand-new capabilities that require a new workflow or module.*

### New Solution 1 — Semi-Structured Data Pipeline (JSON / HTML / Markdown)
**Source**: Survey Section 3

**The Problem**: Users want to analyze their JSON API exports (e.g., REST API responses, config files, exported reports) or HTML tables from web dashboards. Current system only handles flat CSVs and relational SQL.

**Proposed Architecture**:
```
User uploads JSON / HTML / Markdown file
         ↓
   [JSON Analyzer Node]  ← Generates Python script to parse hierarchical structure
         ↓
   Flatten → convert to tabular Pandas DataFrame
         ↓
   Existing CSV Pipeline (analysis → visualization → insight)
```

**Key Challenge**: Structure-Aware Tokenization — treat `{"orders": [{"id": 1, "items": [...]}]}` as a hierarchy, not as plain text.

**Priority**: Medium — implement after Priority 1-3 above.

---

### New Solution 2 — Unstructured Data Pipeline (Image Charts, Video, 3D Data)
**Source**: Survey Section 4 (Chart Understanding, Document Layout)

**The Problem**: Users upload PDFs containing embedded bar charts, scatter plots, or tables as images. The current KB pipeline only extracts text — the chart data is lost.

**Proposed Architecture**:
```
User uploads PDF with charts/images
         ↓
    [Layout Analyzer]  ← Identifies pages with chart images
         ↓
    [Chart-to-Table]   ← VLM (Vision LLM) converts chart image to structured table JSON
         ↓
    Table stored in Qdrant with data card
         ↓
    User can ask: "Analyze the revenue chart from the 2024 Annual Report"
```

**Key Component Needed**: Integration with a Vision LLM (e.g., Gemini Vision, GPT-4V) for chart extraction.

**Priority**: Low for now — requires external Vision API integration. Good for v3.

---

### New Solution 3 — Heterogeneous Full Fusion (SQL + PDF + JSON simultaneously)
**Source**: Survey Section 5 (Symphony, XMODE, AgenticData frameworks)

**The Problem**: Users ask complex questions that span *multiple data modalities*. Example: "Why did Michigan sales drop last month?" requires SQL *and* internal PDF reports simultaneously.

**Current State**: KB context only informs SQL generation, not the final insight.
**Proposed New Workflow**:

```
User Question: "Why did Michigan sales drop?"
         ↓
    [HybridCoordinator Agent]
         ├──► [Quant Path]  → SQL pipeline → "Michigan: -23% MoM" 
         └──► [Qual Path]   → RAG (PDF/Docs) → "Warehouse flood on Mar 5th"
         ↓
    [Fusion Insight Agent] → Merges both into: "Sales dropped 23% due to warehouse flood"
         ↓
    [Output Assembler] → Chart (from SQL) + Narrative (from fusion)
```

**Key New Components**:
1. `HybridCoordinator Agent` — decides to run Quant + Qual in parallel.
2. `Fusion Insight Agent` — replaces the current `insight_agent` with a version that explicitly receives both `sql_data` and `kb_context` as separate labeled inputs.
3. `AnalysisState` extension — add `qual_context: Optional[str]` field.

**Priority**: High Strategic Value. Start after Priority 1 (which is the first step of this).

---

---
---

## PART C: Strategic Product Features (from Unified Master Plan)
*Business-level capabilities that require new infrastructure or cross-cutting services. Not from the papers — from our own product vision.*

### C1 — Unified Ingestion Factory (ZIP / JSON / API Hub)
- **What**: A single entry point that accepts `.zip` archives, JSON exports, or direct API endpoints and auto-routes each file to the correct pipeline (CSV/SQL/KB).
- **Current state**: Users manually upload one file at a time.
- **Gap**: Enterprise clients have archives of hundreds of files to load.
- **Files To Create**: `app/infrastructure/adapters/ingestion_factory.py`, update `knowledge_router`.
- **Example**: Client drops `Q3_Archive.zip` with 50 PDFs + 10 CSVs — system auto-extracts, identifies formats, and ingests all in parallel.
- **Priority**: 🔥 High

---

### C2 — SHA-256 Document Deduplication
- **What**: Before ingesting any file into Qdrant, compute a SHA-256 hash and check if that hash already exists. Skip if duplicate.
- **Current state**: No deduplication — same file can be ingested multiple times, creating vector duplicates.
- **Gap**: One duplicate causes contradictory RAG retrieval and wastes processing costs.
- **Files To Modify**: `app/infrastructure/adapters/qdrant.py`, `knowledge_router`.
- **Example**: Manager uploads "Policy_v2.pdf" twice — second upload detected instantly, processing cancelled, zero cost.
- **Priority**: 🔥 High

---

### C3 — Semantic Analytics Cache (Redis + Vector Similarity)
- **What**: Cache completed analysis job results (chart JSON + insight text) keyed by semantic meaning of the question. Serve from cache if a future question is semantically similar.
- **Current state**: Every question triggers a full LangGraph pipeline execution.
- **Gap**: Repeated or similar questions waste LLM tokens and take 10-30 seconds each.
- **Files To Create**: `app/infrastructure/cache.py`, update `use_cases/analysis/run_pipeline.py`.
- **Example**: User A asks "Revenue in London?" → computed and cached. User B asks "Show London income this year?" → served instantly from cache (cosine similarity > 0.92) for $0.00.
- **Priority**: 🔥 High

---

### C4 — RAG-Powered Schema Mapper (Legacy DB Intelligence)
- **What**: A dedicated Qdrant collection where users can upload a "Data Dictionary" PDF that maps cryptic legacy table/column names to business concepts. The `intake_agent` retrieves this before planning.
- **Current state**: `sql_schema_discovery` shows raw column names (e.g., `Tbl_Cust_V2`, `acct_ref_no_01`).
- **Gap**: LLM fails on poorly-named legacy databases without context.
- **Files To Modify**: `modules/shared/utils/retrieval.py`, `modules/shared/agents/intake_agent.py`.
- **Example**: User asks "Who are our VIP customers?" → Schema Mapper KB returns: *"VIPs = users with `status_level > 5` in table `User_Meta_01`"* → correct SQL generated first try.
- **Priority**: 🔥🔥 Medium-High

---

### C5 — Automated Data Cleaning Rules (RAG-Driven Standards)
- **What**: A RAG collection for "Data Governance Rules" — the cleaning agent retrieves company-specific transformation rules before writing Pandas code.
- **Current state**: `data_cleaning_agent.py` (CSV pipeline) applies generic heuristics.
- **Gap**: Each company has unique standards (e.g., "Always convert EUR and BRL to USD using the internal rate table.").
- **Files To Modify**: `modules/csv/agents/data_cleaning_agent.py`, `modules/shared/utils/retrieval.py`.
- **Example**: Cleaning agent retrieves rule: *"Date format must be ISO 8601 (YYYY-MM-DD)"* and applies it automatically across all date columns.
- **Priority**: 🟡 Medium

---

### C6 — Historical Insight Memory (Long-Term Learning)
- **What**: After every successful analysis, store the generated `executive_summary` + `question` as a new vector in a dedicated "Managerial Memory" Qdrant collection. The `insight_agent` retrieves past relevant insights before writing new ones.
- **Current state**: Every analysis starts from zero — no memory of past findings.
- **Gap**: AI cannot spot trends across time or say "this is different from last quarter."
- **Files To Modify**: `output_assembler.py` (write memory), `insight_agent.py` (read memory).
- **Example**: "Last quarter we found this same spike was driven by the Spring Sale. Today's spike pattern differs — it appears to be organic social media virality."
- **Priority**: 🟡 Medium

---

### C7 — Competitive Intelligence & Market Benchmarking
- **What**: A RAG collection for external market research PDFs. The `recommendation_agent` retrieves industry benchmarks and compares them against internal SQL results.
- **Current state**: Recommendations are based only on internal data patterns.
- **Gap**: No external reality check — AI cannot tell if performance is good or bad relative to the market.
- **Files To Modify**: `modules/sql/agents/recommendation_agent.py`, `modules/shared/utils/retrieval.py`.
- **Example**: "Your 5% growth margin is above last quarter. However, the 'Retail Industry Report 2024' (KB) shows the sector average is 7%, highlighting an optimization gap."
- **Priority**: 🟢 Low (v3 feature)

---
---

## Master Implementation Summary Table

| ID | Feature | Source | Type | Key File(s) | Difficulty | Priority |
|:---:|:---|:---:|:---|:---|:---:|:---:|
| A1 | Hybrid Insight Fusion | Papers | Enhancement | `insight_agent.py` | ⭐ | 🔥 |
| A2 | Content Retrieval | Papers | Enhancement | `sql_schema_discovery.py` | ⭐⭐ | 🔥 |
| A3 | Verifier Node | Papers | Enhancement | `workflow.py` | ⭐⭐ | 🔥 |
| C1 | Unified Ingestion Factory | Master Plan | New Service | `ingestion_factory.py` | ⭐⭐⭐ | 🔥 |
| C2 | SHA-256 Deduplication | Master Plan | Enhancement | `qdrant.py` | ⭐ | 🔥 |
| C3 | Semantic Analytics Cache | Master Plan | New Service | `cache.py`, `run_pipeline.py` | ⭐⭐⭐ | 🔥 |
| A4 | Context-Aware Debugger | Papers | Enhancement | `analysis_agent.py` | ⭐ | 🔥🔥 |
| A5 | Backtracking Router | Papers | Enhancement | `workflow.py` | ⭐⭐ | 🔥🔥 |
| A6 | Execution-Based File Analyzer | Papers | Enhancement | `knowledge_router` | ⭐⭐⭐ | 🔥🔥 |
| C4 | RAG Schema Mapper | Master Plan | Enhancement | `intake_agent.py` | ⭐⭐ | 🔥🔥 |
| C5 | Data Cleaning Rules (RAG) | Master Plan | Enhancement | `data_cleaning_agent.py` | ⭐⭐ | 🟡 |
| C6 | Historical Insight Memory | Master Plan | New Service | `output_assembler.py`, `insight_agent.py` | ⭐⭐⭐ | 🟡 |
| B1 | JSON / HTML Pipeline | Papers | New Pipeline | `modules/json/` (new) | ⭐⭐⭐ | 🟡 |
| B3 | Full Heterogeneous Fusion | Papers + Plan | New Workflow | `modules/hybrid/` (new) | ⭐⭐⭐⭐ | � |
| C7 | Competitive Benchmarking | Master Plan | Enhancement | `recommendation_agent.py` | ⭐⭐ | 🟢 |
| B2 | Chart-to-Table (Vision) | Papers | New Pipeline | `modules/vision/` (new) | ⭐⭐⭐⭐ | � |
