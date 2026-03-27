"""SQL Pipeline — Visualization Agent.

Generates premium Plotly.js Figure configurations dynamically via LLM.
"""

from __future__ import annotations

import json
import re
import structlog
from typing import Any, Dict

logger = structlog.get_logger(__name__)

from app.infrastructure.llm import get_llm
from app.domain.analysis.entities import AnalysisState

# ── Design Token Constants ────────────────────────────────────────────────────
_COLORWAY = ["#6366f1", "#10b981", "#f43f5e", "#fbbf24", "#8b5cf6", "#06b6d4"]
_FONT_FAMILY = '"Inter", "system-ui", sans-serif'
_FONT_COLOR = "#f8fafc"
_GRID_COLOR = "rgba(255,255,255,0.05)"
_TRANSPARENT = "rgba(0,0,0,0)"

# ── LLM Prompt ────────────────────────────────────────────────────────────────
PLOTLY_VIZ_PROMPT = """You are a Principal Data Scientist and Visualization Architect specializing in Plotly.js.
Your task is to design a premium, insight-driven Plotly Figure JSON configuration for a dark-mode analytics dashboard.

---
### CHART SELECTION HEURISTICS
Choose the SINGLE most statistically powerful chart type from the rules below:

| Scenario                                    | Plotly Trace Type         | Notes                                      |
|---------------------------------------------|---------------------------|--------------------------------------------|
| Time-series or sequential trends            | scatter (mode="lines")    | Use x_col = date/time column               |
| Categorical comparisons (3–12 categories)   | bar                       | orientation="v" by default                 |
| Single total or executive KPI               | indicator                 | Use mode="number" or "number+delta"        |
| Part-to-whole / proportions (≤ 7 segments)  | pie                       | Add hole=0.45 for a modern donut style     |
| Hierarchical / nested categories            | treemap                   | Use labels + parents + values              |
| Correlation between 3 numeric metrics       | scatter (with marker.size)| Bubble chart variant                       |
| Multi-metric entity profiling               | scatterpolar              | Radar / spider chart                       |
| Distribution of a numeric column            | histogram                 | Use nbinsx=20                              |
| Raw data / last resort                      | table                     | Use only if no chart fits                  |

---
### STRICT OUTPUT FORMAT
You MUST return a single, valid JSON object with exactly two keys:

1. `"should_visualize"` (boolean): `true` if a chart meaningfully enhances understanding.
   Set to `false` ONLY for trivial results (single row, schema description, 2-item list).

2. `"figure"` (object): A complete Plotly Figure with `"data"` and `"layout"` keys.
   - `"data"`: Array of one or more trace objects.
   - `"layout"`: Axis labels, title, and cosmetic keys (do NOT include colors — those are injected server-side).

---
### TRACE CONSTRUCTION RULES
- ALL column values used in traces MUST come verbatim from the `Schema/Columns` list below. Never invent column names.
- For `bar` / `scatter` traces, set `"x"` and `"y"` to the *arrays of values* extracted from the data sample.
- For `pie` traces, set `"labels"` and `"values"` to the corresponding arrays.
- For `indicator`, set `"value"` to the single numeric result.
- For `treemap`, provide `"labels"`, `"parents"`, and `"values"` arrays.
- Keep `"name"` on each trace equal to the column or category it represents.

---
### LAYOUT RULES
- Set `"title.text"` to a concise, insightful chart title (not the raw question).
- Set axis `"title.text"` to human-readable column labels.
- Do NOT set colors, fonts, paper_bgcolor, plot_bgcolor — those are injected by the server.

---
### EXAMPLES

**Example A — Bar Chart**
```json
{{
  "should_visualize": true,
  "figure": {{
    "data": [
      {{
        "type": "bar",
        "name": "Revenue",
        "x": ["North", "South", "East", "West"],
        "y": [120000, 95000, 143000, 87000]
      }}
    ],
    "layout": {{
      "title": {{"text": "Revenue by Region"}},
      "xaxis": {{"title": {{"text": "Region"}}}},
      "yaxis": {{"title": {{"text": "Revenue (USD)"}}}}
    }}
  }}
}}
```

**Example B — Donut Pie**
```json
{{
  "should_visualize": true,
  "figure": {{
    "data": [
      {{
        "type": "pie",
        "labels": ["Electronics", "Apparel", "Food", "Books"],
        "values": [45, 25, 20, 10],
        "hole": 0.45
      }}
    ],
    "layout": {{
      "title": {{"text": "Sales Share by Category"}}
    }}
  }}
}}
```

**Example C — KPI Indicator**
```json
{{
  "should_visualize": true,
  "figure": {{
    "data": [
      {{
        "type": "indicator",
        "mode": "number",
        "value": 4821053,
        "title": {{"text": "Total Orders"}}
      }}
    ],
    "layout": {{
      "title": {{"text": "Total Orders (All Time)"}}
    }}
  }}
}}
```

**Example D — No Chart**
```json
{{
  "should_visualize": false,
  "figure": null
}}
```

---
### INPUT CONTEXT

**Intent**: {intent}
**User Question**: {question}
**SQL Query**:
```sql
{sql}
```
**Schema / Columns**: {columns}
**Data Sample** (up to 10 rows):
```json
{data}
```

---
Return ONLY a valid JSON object. NO markdown fences. NO explanation. NO preamble.
"""

# ── Premium Dark-Mode Layout Defaults ─────────────────────────────────────────
_BASE_LAYOUT: Dict[str, Any] = {
    "paper_bgcolor": _TRANSPARENT,
    "plot_bgcolor": _TRANSPARENT,
    "font": {
        "family": _FONT_FAMILY,
        "color": _FONT_COLOR,
        "size": 13,
    },
    "colorway": _COLORWAY,
    "hovermode": "x unified",
    "hoverlabel": {
        "bgcolor": "rgba(15,15,30,0.9)",
        "bordercolor": "rgba(255,255,255,0.15)",
        "font": {"family": _FONT_FAMILY, "color": _FONT_COLOR, "size": 12},
    },
    "legend": {
        "bgcolor": "rgba(255,255,255,0.04)",
        "bordercolor": "rgba(255,255,255,0.08)",
        "borderwidth": 1,
        "font": {"color": _FONT_COLOR},
    },
    "margin": {"l": 60, "r": 30, "t": 60, "b": 60},
    "xaxis": {
        "gridcolor": _GRID_COLOR,
        "linecolor": "rgba(255,255,255,0.1)",
        "tickfont": {"color": _FONT_COLOR},
        "title": {"font": {"color": _FONT_COLOR}},
        "zerolinecolor": "rgba(255,255,255,0.08)",
    },
    "yaxis": {
        "gridcolor": _GRID_COLOR,
        "linecolor": "rgba(255,255,255,0.1)",
        "tickfont": {"color": _FONT_COLOR},
        "title": {"font": {"color": _FONT_COLOR}},
        "zerolinecolor": "rgba(255,255,255,0.08)",
    },
    "title": {
        "font": {"family": _FONT_FAMILY, "color": _FONT_COLOR, "size": 18},
        "x": 0.04,
        "xanchor": "left",
    },
}

_RESPONSIVE_CONFIG: Dict[str, Any] = {"responsive": True, "displayModeBar": False}


# ── Main Agent ─────────────────────────────────────────────────────────────────
async def visualization_agent(state: AnalysisState) -> Dict[str, Any]:
    """Analyze SQL results via LLM and return a premium Plotly Figure JSON."""

    analysis = state.get("analysis_results") or {}
    if not analysis or not analysis.get("data"):
        logger.warning("visualization_no_data", state_keys=list(state.keys()))
        return {
            "chart_json": None,
            "chart_engine": "plotly",
            "error": "No data available for visualization",
        }

    llm = get_llm(temperature=0)

    raw_data: list = analysis["data"]
    data_sample = raw_data[:50]  # Use up to 50 rows for trace construction
    prompt_sample = raw_data[:10]  # Smaller sample for the prompt context

    clean_question = _sanitize_question(state.get("question", ""))

    prompt = PLOTLY_VIZ_PROMPT.format(
        intent=state.get("intent", "comparison"),
        question=clean_question,
        sql=state.get("generated_sql", ""),
        columns=json.dumps(analysis.get("columns", [])),
        data=json.dumps(prompt_sample, indent=2, default=str),
    )

    content: str | None = None
    try:
        response = await llm.ainvoke(prompt)
        content = response.content
        logger.info("llm_visualization_response_received", job_id=state.get("job_id"))

        viz_config = _parse_json(content)

        # ── Necessity check ───────────────────────────────────────────────────
        if not viz_config.get("should_visualize", True):
            logger.info("visualization_skipped_per_agent", job_id=state.get("job_id"))
            return {"chart_json": None, "chart_engine": "plotly"}

        figure = viz_config.get("figure")
        if not figure or not isinstance(figure, dict) or not figure.get("data"):
            logger.warning("invalid_plotly_figure_from_llm", content=content)
            figure = _build_fallback_table(analysis)

        # ── Hydrate figure with full data (LLM only sees 10 rows) ─────────────
        figure = _hydrate_traces(figure, data_sample, analysis.get("columns", []))

        # ── Merge premium dark-mode layout ────────────────────────────────────
        figure["layout"] = _deep_merge(_BASE_LAYOUT, figure.get("layout") or {})
        figure["config"] = _RESPONSIVE_CONFIG

        logger.info(
            "plotly_figure_built",
            job_id=state.get("job_id"),
            trace_count=len(figure["data"]),
            viz_type=figure["data"][0].get("type") if figure["data"] else "unknown",
        )

        return {"chart_json": figure, "chart_engine": "plotly"}

    except Exception as exc:
        logger.error(
            "plotly_generation_failed",
            error=str(exc),
            content=content,
            exc_info=True,
        )
        return {
            "chart_json": None,
            "chart_engine": "plotly",
            "error": f"Plotly visualization failed: {exc}",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_question(q: str) -> str:
    """Extract plain text from JSON-encoded question payloads (e.g. LangGraph history)."""
    try:
        parsed = json.loads(q)
        if isinstance(parsed, dict) and "text" in parsed:
            return parsed["text"]
    except (json.JSONDecodeError, TypeError):
        pass
    return q


def _hydrate_traces(
    figure: Dict[str, Any],
    full_data: list,
    columns: list,
) -> Dict[str, Any]:
    """
    Replace LLM-generated stub arrays in traces with the actual full dataset rows.

    The LLM sees only 10 rows; this function re-maps x/y/values/labels onto
    up to 50 rows using the column names it declared.
    """
    if not full_data or not figure.get("data"):
        return figure

    col_index: Dict[str, list] = {}
    if full_data and isinstance(full_data[0], (list, tuple)):
        # Columnar format: list of rows → transpose by column index
        for idx, col_name in enumerate(columns):
            col_index[col_name] = [row[idx] for row in full_data if idx < len(row)]
    elif full_data and isinstance(full_data[0], dict):
        # Dict format: list of {col: val} dicts
        for col_name in columns:
            col_index[col_name] = [row.get(col_name) for row in full_data]

    for trace in figure["data"]:
        trace_type = trace.get("type", "")

        # Bar / Scatter: re-map x and y
        if trace_type in ("bar", "scatter", "histogram"):
            x_vals = _resolve_col(trace.get("x"), col_index)
            y_vals = _resolve_col(trace.get("y"), col_index)
            if x_vals is not None:
                trace["x"] = x_vals
            if y_vals is not None:
                trace["y"] = y_vals

        # Pie / Donut
        elif trace_type == "pie":
            labels = _resolve_col(trace.get("labels"), col_index)
            values = _resolve_col(trace.get("values"), col_index)
            if labels is not None:
                trace["labels"] = labels
            if values is not None:
                trace["values"] = values

        # Treemap
        elif trace_type == "treemap":
            for key in ("labels", "parents", "values"):
                resolved = _resolve_col(trace.get(key), col_index)
                if resolved is not None:
                    trace[key] = resolved

        # Radar / Scatterpolar
        elif trace_type == "scatterpolar":
            r_vals = _resolve_col(trace.get("r"), col_index)
            theta_vals = _resolve_col(trace.get("theta"), col_index)
            if r_vals is not None:
                trace["r"] = r_vals
            if theta_vals is not None:
                trace["theta"] = theta_vals

    return figure


def _resolve_col(
    current_value: Any,
    col_index: Dict[str, list],
) -> list | None:
    """
    If `current_value` is a column name string present in col_index, return
    the full column array. Otherwise return None (keep as-is).
    """
    if isinstance(current_value, str) and current_value in col_index:
        return col_index[current_value]
    return None


def _build_fallback_table(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Return a minimal Plotly Table trace when LLM output is invalid."""
    columns = analysis.get("columns", [])
    rows = analysis.get("data", [])[:50]

    if rows and isinstance(rows[0], dict):
        cell_values = [[row.get(c, "") for row in rows] for c in columns]
    elif rows and isinstance(rows[0], (list, tuple)):
        cell_values = [[row[i] if i < len(row) else "" for row in rows] for i in range(len(columns))]
    else:
        cell_values = []

    return {
        "data": [
            {
                "type": "table",
                "header": {
                    "values": columns,
                    "fill": {"color": "rgba(99,102,241,0.25)"},
                    "font": {"color": _FONT_COLOR, "size": 12},
                    "align": "left",
                    "line": {"color": "rgba(255,255,255,0.08)"},
                },
                "cells": {
                    "values": cell_values,
                    "fill": {"color": ["rgba(255,255,255,0.03)", "rgba(255,255,255,0.01)"]},
                    "font": {"color": _FONT_COLOR, "size": 12},
                    "align": "left",
                    "line": {"color": "rgba(255,255,255,0.05)"},
                },
            }
        ],
        "layout": {"title": {"text": "Query Results"}},
    }


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merge `override` into `base`, giving priority to `override`
    for scalar values while preserving nested dict merging.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _parse_json(content: Any) -> Dict[str, Any]:
    """Ultra-resilient JSON parser for LLM responses."""
    if not isinstance(content, str) or not content.strip():
        return {}

    content = content.strip()
    start_idx = content.find("{")
    end_idx = content.rfind("}")

    if start_idx == -1 or end_idx == -1:
        return {}

    json_str = content[start_idx : end_idx + 1]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    try:
        cleaned = re.sub(r",\s*([\]}])", r"\1", json_str)
        cleaned = re.sub(r"[\x00-\x1F\x7F]", "", cleaned)
        return json.loads(cleaned)
    except Exception:
        pass

    return {}