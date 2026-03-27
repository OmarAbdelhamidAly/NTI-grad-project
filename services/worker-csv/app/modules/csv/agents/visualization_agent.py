"""CSV Pipeline — Visualization Agent.

Generates premium Plotly.js Figure configurations dynamically via LLM for CSV data.
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

# ── Design Token Constants ────────────────────────────────────────────────────
_COLORWAY = ["#6366f1", "#10b981", "#f43f5e", "#fbbf24", "#8b5cf6", "#06b6d4"]
_FONT_FAMILY = '"Inter", "system-ui", sans-serif'
_FONT_COLOR = "#f8fafc"
_GRID_COLOR = "rgba(255,255,255,0.05)"
_TRANSPARENT = "rgba(0,0,0,0)"

# ── LLM Prompt ────────────────────────────────────────────────────────────────
PLOTLY_VIZ_PROMPT = """You are a Principal Data Scientist and Visualization Architect specializing in Plotly.js.
Your task is to design a premium, insight-driven Plotly Figure JSON configuration for a dark-mode analytics dashboard based on CSV data analysis.

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
| Correlation between 2-3 numeric metrics     | scatter                   | Use mode="markers"                         |
| Multi-metric entity profiling               | scatterpolar              | Radar / spider chart                       |
| Distribution of a numeric column            | histogram                 | Use nbinsx=20                              |

---
### STRICT OUTPUT FORMAT
You MUST return a single, valid JSON object with exactly two keys:

1. `"should_visualize"` (boolean): `true` if a chart meaningfully enhances understanding.
   Set to `false` ONLY for trivial results (single row, raw schema description).

2. `"figure"` (object): A complete Plotly Figure with `"data"` and `"layout"` keys.
   - `"data"`: Array of one or more trace objects.
   - `"layout"`: Axis labels, title, and cosmetic keys (do NOT include colors — those are injected server-side).

---
### TRACE CONSTRUCTION RULES
- ALL column values used in traces MUST come verbatim from the `Columns` list below.
- For `bar` / `scatter` traces, set `"x"` and `"y"` to the *column name strings*.
- For `pie` traces, set `"labels"` and `"values"` to the *column name strings*.
- Set `"name"` on each trace equal to the column or category it represents.

---
### LAYOUT RULES
- Set `"title.text"` to a concise, insightful chart title.
- Set axis `"title.text"` to human-readable labels.
- Do NOT set colors, fonts, backgrounds — those are injected automatically.

---
### INPUT CONTEXT

**Intent**: {intent}
**User Question**: {question}
**Pandas Action**: {plan_summary}
**Columns**: {columns}
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


async def visualization_agent(state: AnalysisState) -> Dict[str, Any]:
    """Generate a native Plotly Figure configuration for CSV data."""
    analysis = state.get("analysis_results") or {}
    df_data = analysis.get("data") or analysis.get("dataframe")
    
    if not analysis or not df_data:
        logger.warning("visualization_skipped_no_data", job_id=state.get("job_id"))
        return {"chart_json": None, "chart_engine": "plotly"}

    llm = get_llm(temperature=0)
    data_sample = df_data[:10]
    
    plan = analysis.get("plan") or {}
    plan_summary = plan.get("summary") or plan.get("operation", "Custom analysis")

    prompt = PLOTLY_VIZ_PROMPT.format(
        intent=state.get("intent", "comparison"),
        question=state.get("question", "Analysis"),
        plan_summary=plan_summary,
        columns=json.dumps(analysis.get("columns", [])),
        data=json.dumps(data_sample, indent=2, default=str),
    )

    content: str | None = None
    try:
        response = await llm.ainvoke(prompt)
        content = response.content
        viz_config = _parse_json(content)

        if not viz_config.get("should_visualize", True):
            return {"chart_json": None, "chart_engine": "plotly"}

        figure = viz_config.get("figure")
        if not figure or not isinstance(figure, dict) or not figure.get("data"):
            figure = _build_fallback_chart(analysis, df_data)

        # ── Hydrate figure with full data ────────────────────────────────────
        figure = _hydrate_traces(figure, df_data, analysis.get("columns", []))

        # ── Merge premium dark-mode layout ────────────────────────────────────
        figure["layout"] = _deep_merge(_BASE_LAYOUT, figure.get("layout") or {})
        figure["config"] = _RESPONSIVE_CONFIG

        return {
            "chart_json": figure,
            "chart_engine": "plotly"
        }

    except Exception as e:
        logger.error("csv_visualization_failed", error=str(e), content=content)
        return {
            "chart_json": _build_fallback_chart(analysis, df_data),
            "chart_engine": "plotly",
            "error": str(e)
        }

# ── Helpers ───────────────────────────────────────────────────────────────────

def _hydrate_traces(figure: Dict[str, Any], full_data: list, columns: list) -> Dict[str, Any]:
    """Replace col names with actual data arrays."""
    if not full_data or not figure.get("data"):
        return figure

    col_index: Dict[str, list] = {}
    if full_data and isinstance(full_data[0], dict):
        for col_name in columns:
            col_index[col_name] = [row.get(col_name) for row in full_data]

    for trace in figure["data"]:
        t_type = trace.get("type", "")
        for key in ["x", "y", "labels", "values", "r", "theta"]:
            if key in trace and isinstance(trace[key], str) and trace[key] in col_index:
                trace[key] = col_index[trace[key]]
    
    return figure

def _build_fallback_chart(analysis: Dict[str, Any], df_data: list) -> Dict[str, Any]:
    """Basic Bar Chart Fallback."""
    cols = analysis.get("columns", [])
    if len(cols) < 2 or not df_data:
        return {"data": [], "layout": {"title": {"text": "Insufficient data"}}}
    
    x_col, y_col = cols[0], cols[1]
    return {
        "data": [{
            "x": [r.get(x_col) for r in df_data[:20]],
            "y": [r.get(y_col) for r in df_data[:20]],
            "type": "bar",
            "name": y_col
        }],
        "layout": {"title": {"text": f"{y_col} by {x_col}"}}
    }

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result

def _parse_json(content: Any) -> Dict[str, Any]:
    if not isinstance(content, str) or not content.strip():
        return {}
    content = content.strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match: return {}
    json_str = match.group()
    try:
        return json.loads(json_str)
    except:
        cleaned = re.sub(r",\s*([\]}])", r"\1", json_str)
        try: return json.loads(cleaned)
        except: return {}
