"""SQL Pipeline — Reflection Agent.

Analyzes execution errors or empty results and attempts to repair the SQL query.
Uses schema context (tables, columns, samples) to perform semantic mapping repairs.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from app.domain.analysis.entities import AnalysisState
from app.infrastructure.llm import get_llm

REFLECTION_PROMPT = """You are a senior SQL expert and self-correction agent.
The previous SQL query FAILED or yielded zero rows. Your task is to analyze the error and the database schema, then provide a REPAIRED SQL QUERY.

STRICT RULES:
1. If the error is "Column not found", find the most semantically similar column in the schema.
2. If the result was empty, check if filters/WHERE clauses were too restrictive or case-sensitive.
3. If the grammar was wrong, fix it.
4. Respond ONLY with a JSON object containing the repaired query.

SCHEMA CONTEXT:
{schema_context}

PREVIOUS QUERY:
{previous_query}

ERROR/ISSUE:
{error}

REPAIRED QUERY (JSON):
{{
  "query": "...",
  "explanation": "..."
}}"""

async def reflection_agent(state: AnalysisState) -> Dict[str, Any]:
    """Analyze the error and the schema to repair the SQL query."""
    error = state.get("error") or state.get("reflection_context")
    if not error:
        return {}

    retry_count = state.get("retry_count", 0)
    if retry_count >= 3:
        return {"error": f"Max retries reached. Last error: {error}"}

    # Build schema context for the LLM
    schema = state.get("schema_summary", {})
    tables = schema.get("tables", [])
    schema_context = "AVAILABLE SCHEMA:\n"
    for table in tables:
        schema_context += f"Table: {table['table']}\n"
        for col in table.get("columns", []):
            schema_context += f"  - {col['name']} ({col['type']}) | samples: {col.get('low_cardinality_values', [])}\n"

    previous_query = state.get("generated_sql") or "No query generated yet."
    
    llm = get_llm(temperature=0)
    prompt = REFLECTION_PROMPT.format(
        schema_context=schema_context,
        previous_query=previous_query,
        error=error
    )
    
    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        
        # Clean markdown if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        
        repaired_data = json.loads(content)
        repaired_query = repaired_data.get("query")
        
        return {
            "generated_sql": repaired_query,
            "error": None,
            "reflection_context": None, # Clear context for next run
            "retry_count": retry_count + 1
        }
    except Exception as e:
        return {"error": f"Reflection failed to repair query: {str(e)}"}
