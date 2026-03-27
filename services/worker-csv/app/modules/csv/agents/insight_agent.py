"""CSV Pipeline — Insight Agent.

Generates written analysis and executive summary from CSV analysis results.
Learned from the high-performance SQL implementation.
"""

from __future__ import annotations

import json
import re
import structlog
from typing import Any, Dict

logger = structlog.get_logger(__name__)

from app.infrastructure.llm import get_llm
from app.domain.analysis.entities import AnalysisState
from app.infrastructure.config import settings

INSIGHT_PROMPT = """You are a senior data analyst writing insights for business stakeholders.

### FORMATTING RULES (STRICT)
1. You MUST respond with ONLY a valid JSON object.
2. The `insight_report` and `executive_summary` fields MUST contain RAW text without markdown code blocks (no ```) inside the string values.
3. DO NOT wrap the text in curly braces {{}} or extra quotes.
4. If there is no data, explain why clearly in the report.

### REQUIRED JSON STRUCTURE
{{
  "insight_report": "Direct analysis text here. Use bullet points or paragraphs as needed.",
  "executive_summary": "One or two punchy sentences for a busy executive."
}}

Question: {question}
Intent: {intent}
Data: {data}

{complexity_instruction}"""


async def insight_agent(state: AnalysisState) -> Dict[str, Any]:
    """Generate written analysis and executive summary from CSV results."""
    analysis = state.get("analysis_results") or {}
    if not analysis:
        error_msg = state.get("error") or "No analysis data available."
        return {
            "insight_report": f"Analysis could not be completed. Details: {error_msg}",
            "executive_summary": "Analysis could not be completed.",
        }

    llm = get_llm(temperature=0.3)

    # Calculate complexity instructions
    idx = state.get("complexity_index", 1)
    tot = state.get("total_pills", 1)
    
    complexity_instruction = ""
    if tot > 1:
        if idx == 1:
            complexity_instruction = "TONE: Tactical & Foundational. Focus on the immediate facts."
        elif idx == tot:
            complexity_instruction = f"TONE: Strategic & Executive. Synthesis of implications."
        else:
            complexity_instruction = f"TONE: Investigative & Advanced. Dig into the 'why'."

    def _sanitize_question(q: str) -> str:
        """Extract text from JSON questions if they have history."""
        try:
            parsed = json.loads(q)
            if isinstance(parsed, dict) and "text" in parsed:
                return parsed["text"]
        except:
            pass
        return q

    clean_question = _sanitize_question(state.get("question") or "")
    
    # Use 'data' or 'dataframe'
    df_data = analysis.get("data") or analysis.get("dataframe") or []

    prompt = INSIGHT_PROMPT.format(
        question=clean_question,
        intent=state.get("intent", "comparison"),
        data=json.dumps(df_data[:20], indent=2, default=str),
        complexity_instruction=complexity_instruction
    )

    content: str | None = None
    try:
        response = await llm.ainvoke(prompt)
        content = response.content
        parsed = _parse_json(content)

        if not parsed:
            logger.warning("csv_insight_parsing_empty", content=content)
            raise ValueError("Parsed insight JSON is empty")

        return {
            "insight_report": parsed.get("insight_report", "Analysis completed."),
            "executive_summary": parsed.get("executive_summary", "See detailed report."),
        }
    except Exception as e:
        logger.error("csv_insight_generation_failed", error=str(e), content=content)
        return {
            "insight_report": f"Analysis was performed but insight generation encountered an error: {str(e)[:100]}",
            "executive_summary": "Results are available in chart form.",
        }


def _parse_json(content: str) -> Dict[str, str]:
    """Extract JSON object from LLM response with fallback extraction."""
    if not isinstance(content, str) or not content.strip():
        return {}
    
    content = content.strip()
    
    # Try to find JSON block first
    json_match = re.search(r'\{[\s\S]*\}', content)
    if json_match:
        try:
            raw_json = json_match.group().strip()
            parsed = json.loads(raw_json)
            for key in ["insight_report", "executive_summary"]:
                if key in parsed and isinstance(parsed[key], str):
                    val = parsed[key].strip()
                    val = re.sub(r'^```[a-z]*\n|```$', '', val, flags=re.MULTILINE)
                    parsed[key] = val
            return parsed
        except json.JSONDecodeError:
            pass
    
    # Fallback: Extract fields using regex
    result = {}
    insight_match = re.search(r'["\']?insight_report["\']?\s*:\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    if insight_match:
        result["insight_report"] = insight_match.group(1)
    
    summary_match = re.search(r'["\']?executive_summary["\']?\s*:\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
    if summary_match:
        result["executive_summary"] = summary_match.group(1)
    
    return result if result else {}
