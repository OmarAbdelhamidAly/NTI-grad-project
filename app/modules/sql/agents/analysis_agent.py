"""SQL Pipeline — Analysis Agent.

Uses an LLM to generate a safe SELECT query, then dispatches it
to the run_sql_query tool for parameterized execution.

Includes retry logic: up to 3 attempts on failure.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from langchain_groq import ChatGroq

from app.domain.analysis.entities import AnalysisState
from app.infrastructure.config import settings
from app.modules.shared.tools.load_data_source import get_connection_string
from app.modules.shared.utils.retrieval import get_kb_context

# ── Prompt ────────────────────────────────────────────────────────────────────

SQL_ANALYSIS_PROMPT = """You are a SQL expert. Given the user question, database schema, and a dictionary of business metrics,
write a safe, read-only SELECT query to answer the question.

Rules:
- Only SELECT queries. No INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE.
- Use parameterised query syntax (:param_name) for any user-supplied values.
- Keep results under 1000 rows using LIMIT.
- Use the table and column names exactly as they appear in the schema.
- **CRITICAL**: Use the "Business Metrics Dictionary" to understand how to calculate specific business terms (like 'active user' or 'revenue'). If a metric has a 'formula', use that logic in your SQL.

Respond ONLY with valid JSON:
{{
  "query": "SELECT ... FROM ... WHERE ... LIMIT 100",
  "params": {{}}
}}

Business Metrics Dictionary:
{metrics}

Schema: {schema}
Question: {question}
Intent: {intent}
Relevant columns: {columns}

Knowledge Base Context (if relevant):
{kb_context}

{error_hint}"""


# ── Main Agent ────────────────────────────────────────────────────────────────

async def analysis_agent(state: AnalysisState) -> Dict[str, Any]:
    """Run the SQL analysis using an LLM-generated SELECT query.

    Includes retry logic: up to 3 attempts on failure.
    The LLM only generates the QUERY — actual execution goes through
    the validated, injection-safe run_sql_query tool.
    """
    retry_count = state.get("retry_count", 0)
    # If this is a retry due to an error, pass the error hint to the model
    error_hint = ""
    if state.get("error"):
        error_hint = f"\n[RETRY HINT] Your previous query failed with this error: {state['error']}\nPlease fix the syntax or logic."
    
    if state.get("policy_violation"):
        error_hint += f"\n[POLICY VIOLATION] Your previous plan was REJECTED for this reason: {state['policy_violation']}\nYou MUST adjust your query to comply with organization policies."

    llm = ChatGroq(
        model_name="llama-3.3-70b-versatile",
        groq_api_key=settings.GROCK_API_KEY,
        temperature=0,
    )

    schema_str = json.dumps(state.get("schema_summary", {}), indent=2)
    intent = state.get("intent", "comparison")
    columns = json.dumps(state.get("relevant_columns", []))

    try:
        return await _run_sql_analysis(
            llm, state, schema_str, intent, columns, error_hint, retry_count
        )
    except Exception as exc:
        return {
            "error": str(exc),
            "retry_count": retry_count + 1,
        }


# ── SQL Analysis ──────────────────────────────────────────────────────────────

async def _run_sql_analysis(
    llm, state, schema_str, intent, columns, error_hint, retry_count
) -> Dict[str, Any]:
    """Generate a SELECT query from the LLM and run it via run_sql_query tool."""
    from app.modules.sql.tools.run_sql_query import run_sql_query

    metrics_str = json.dumps(state.get("business_metrics", []), indent=2)
    # Retrieve Knowledge Base context if kb_id is present
    kb_context = await get_kb_context(state.get("kb_id"), state["question"])

    prompt = SQL_ANALYSIS_PROMPT.format(
        metrics=metrics_str,
        schema=schema_str,
        question=state["question"],
        intent=intent,
        columns=columns,
        kb_context=kb_context or "No relevant document context found.",
        error_hint=error_hint,
    )

    response = await llm.ainvoke(prompt)
    plan = _parse_json(response.content)

    connection_string = get_connection_string(state)
    if not connection_string:
        return {
            "error": "No SQL connection string available. Check your data source configuration.",
            "retry_count": retry_count + 1,
        }

    query = plan.get("query", "")
    params = plan.get("params", {})

    if not query:
        return {
            "error": "LLM did not generate a SQL query.",
            "retry_count": retry_count + 1,
        }

    result = run_sql_query.invoke({
        "connection_string": connection_string,
        "query": query,
        "params": params,
        "limit": 1000,
    })

    return {
        "analysis_results": {
            "plan": {"query": query, "params": params},
            "source_type": "sql",
            **result,
        },
        "error": None,
        "retry_count": retry_count,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json(content: str) -> Dict[str, Any]:
    """Extract and parse JSON from LLM response, stripping markdown fences."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM returned an empty response.")

    content = content.strip()

    if content.startswith("```"):
        lines = content.split("\n")
        inner_lines = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            if line.startswith("```") and in_block:
                break
            if in_block:
                inner_lines.append(line)
        content = "\n".join(inner_lines)

    return json.loads(content)
