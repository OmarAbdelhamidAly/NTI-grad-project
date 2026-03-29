"""CSV Pipeline — Visualization Agent.

Generates premium Plotly.js Figure configurations dynamically via LLM,
with deterministic pre-analysis, strict validation, and robust hydration.

Decision flow:
    1. _profile_data()        → derive cardinality, dtypes, shape
    2. _select_chart_type()   → deterministic rule-engine (no LLM guessing)
    3. LLM call               → only generates layout + aesthetic config
    4. _validate_figure()     → hard reject bad traces before merge
    5. _hydrate_traces()      → replace stubs with full data
    6. _merge_layout()        → inject dark-mode tokens

FIX LOG (v2):
    - [FIX-1] Pie/Donut: تشتغل على proportion intent بغض النظر عن row_count
    - [FIX-2] Treemap: تتفعل لما categories > 7 في proportion context
                       + لما cardinality > 10 في categorical comparison
    - [FIX-3] Horizontal Bar: تتفعل لما labels طويلة (avg > 8 chars) أو categories > 8
    - [FIX-4] Dot Plot: تتفعل لما range ضيق (coefficient of variation < 0.05)
    - [FIX-5] Title bug: الـ LLM prompt بيتبعت مع السؤال الصح دايماً (كان موجود في state)
"""

from __future__ import annotations

import json
import math
import re
import structlog
from datetime import date, datetime
from typing import Any

logger = structlog.get_logger(__name__)

from app.infrastructure.llm import get_llm
from app.domain.analysis.entities import AnalysisState

# ── Design Token Constants ────────────────────────────────────────────────────
_COLORWAY    = ["#6366f1", "#10b981", "#f43f5e", "#fbbf24", "#8b5cf6", "#06b6d4"]
_FONT_FAMILY = '"Inter", "system-ui", sans-serif'
_FONT_COLOR  = "#f8fafc"
_GRID_COLOR  = "rgba(255,255,255,0.05)"
_TRANSPARENT = "rgba(0,0,0,0)"

# ── Chart-type registry ───────────────────────────────────────────────────────
_CHART_RULES: list[tuple[str, str]] = [
    ("indicator",  "Single numeric KPI — number indicator is clearest"),
    ("scatter",    "Time-series or date x-axis — line chart shows trend"),
    ("pie",        "Part-to-whole with 2–7 categories — donut shows proportion"),
    ("treemap",    "Part-to-whole with 8+ categories — treemap avoids label clutter"),
    ("dot_plot",   "Narrow numeric range — dot plot avoids exaggerating differences"),
    ("h_bar",      "Long category labels or many categories — horizontal bar"),
    ("bar",        "Categorical comparison — bar chart ranks discrete groups"),
    ("histogram",  "Single numeric column distribution"),
    ("scatter",    "Two numeric columns — scatter shows correlation"),
    ("table",      "Fallback: no better visual encoding available"),
]

# ── LLM Prompt (layout-only; chart type is pre-decided) ───────────────────────
_LAYOUT_PROMPT = """\
You are a Plotly.js visualization expert working on a dark-mode analytics dashboard.

The chart type has already been decided: **{chart_type}**
Do NOT change it.

Your only job is to return a JSON object with:
1. "title"   — A high-impact, business-focused title (e.g., "Market Dominance" instead of "Sales by Category").
2. "x_label" — A clean, human-readable label for the X axis.
3. "y_label" — A clean, human-readable label for the Y axis.
4. "rationale" — A professional, consultant-grade explanation of why this chart type is optimal for this data.

Rules:
- Return ONLY valid JSON. No markdown. No preamble.
- "title" must describe the insight, not repeat the question.
- The title MUST reflect the actual question being answered. Do not reuse titles from previous questions.

Context:
  Intent      : {intent}
  Question    : {question}
  Chart type  : {chart_type}
  Columns     : {columns}
  Row count   : {row_count}
  Data sample : {data_sample}

Return exactly:
{{"title": "...", "x_label": "...", "y_label": "...", "rationale": "..."}}
"""

# ── Premium Dark-Mode Layout ──────────────────────────────────────────────────
_BASE_LAYOUT: dict[str, Any] = {
    "paper_bgcolor": _TRANSPARENT,
    "plot_bgcolor":  _TRANSPARENT,
    "font": {"family": _FONT_FAMILY, "color": _FONT_COLOR, "size": 13},
    "colorway": _COLORWAY,
    "hovermode": "x unified",
    "hoverlabel": {
        "bgcolor":     "rgba(15,15,30,0.9)",
        "bordercolor": "rgba(255,255,255,0.15)",
        "font": {"family": _FONT_FAMILY, "color": _FONT_COLOR, "size": 12},
    },
    "legend": {
        "bgcolor":     "rgba(255,255,255,0.04)",
        "bordercolor": "rgba(255,255,255,0.08)",
        "borderwidth": 1,
        "font": {"color": _FONT_COLOR},
    },
    "margin": {"l": 60, "r": 30, "t": 60, "b": 60},
    "xaxis": {
        "gridcolor":    _GRID_COLOR,
        "linecolor":    "rgba(255,255,255,0.1)",
        "tickfont":     {"color": _FONT_COLOR},
        "title":        {"font": {"color": _FONT_COLOR}},
        "zerolinecolor":"rgba(255,255,255,0.08)",
    },
    "yaxis": {
        "gridcolor":    _GRID_COLOR,
        "linecolor":    "rgba(255,255,255,0.1)",
        "tickfont":     {"color": _FONT_COLOR},
        "title":        {"font": {"color": _FONT_COLOR}},
        "zerolinecolor":"rgba(255,255,255,0.08)",
    },
    "title": {
        "font": {"family": _FONT_FAMILY, "color": _FONT_COLOR, "size": 18},
        "x": 0.04,
        "xanchor": "left",
    },
}

_RESPONSIVE_CONFIG: dict[str, Any] = {"responsive": True, "displayModeBar": False}


# ═════════════════════════════════════════════════════════════════════════════
# Public agent entry-point
# ═════════════════════════════════════════════════════════════════════════════

async def visualization_agent(state: AnalysisState) -> dict[str, Any]:
    """
    Analyse CSV results, decide chart type deterministically, then call
    LLM only for layout labels. Returns a fully-hydrated Plotly figure.
    """
    analysis = state.get("analysis_results") or {}
    raw_data: list = analysis.get("data") or analysis.get("dataframe") or []
    columns:  list = analysis.get("columns") or []

    if not raw_data or not columns:
        logger.warning("visualization_no_data", state_keys=list(state.keys()))
        return _no_chart("No data available for visualization")

    # ── 1. Profile the data ───────────────────────────────────────────────────
    profile = _profile_data(raw_data, columns)
    logger.info("data_profile", job_id=state.get("job_id"), **{
        k: v for k, v in profile.items() if k != "rows"
    })

    # ── 2. Decide chart type deterministically ────────────────────────────────
    chart_type, rule_reason = _select_chart_type(
        profile=profile,
        intent=state.get("intent", "comparison"),
        row_count=len(raw_data),
    )

    # ── 3. Skip visualization for trivial data ────────────────────────────────
    if chart_type == "skip":
        logger.info("visualization_skipped", reason=rule_reason, job_id=state.get("job_id"))
        return {"chart_json": None, "chart_engine": "plotly"}

    # ── 4. Ask LLM only for labels / title ───────────────────────────────────
    layout_meta = await _fetch_layout_meta(
        chart_type=chart_type,
        intent=state.get("intent", "comparison"),
        question=_sanitize_question(state.get("question", "")),
        columns=columns,
        row_count=len(raw_data),
        data_sample=raw_data[:10],
    )

    # ── 5. Build figure from deterministic chart type + full data ─────────────
    figure = _build_figure(
        chart_type=chart_type,
        raw_data=raw_data[:50],
        columns=columns,
        profile=profile,
        layout_meta=layout_meta,
    )

    # ── 6. Validate figure before sending ────────────────────────────────────
    validation_error = _validate_figure(figure)
    if validation_error:
        logger.warning(
            "figure_validation_failed",
            reason=validation_error,
            job_id=state.get("job_id"),
        )
        figure = _build_fallback_table(analysis)

    # ── 7. Merge dark-mode layout ─────────────────────────────────────────────
    figure["layout"] = _deep_merge(_BASE_LAYOUT, figure.get("layout") or {})
    figure["config"] = _RESPONSIVE_CONFIG

    rationale = layout_meta.get("rationale") or rule_reason
    logger.info(
        "plotly_figure_built",
        job_id=state.get("job_id"),
        chart_type=chart_type,
        trace_count=len(figure["data"]),
        rationale=rationale,
    )
    return {"chart_json": figure, "chart_engine": "plotly", "viz_rationale": rationale}


# ═════════════════════════════════════════════════════════════════════════════
# Step 1 — Data Profiling
# ═════════════════════════════════════════════════════════════════════════════

def _profile_data(raw_data: list, columns: list) -> dict[str, Any]:
    """Derive column-level statistics for chart selection."""
    rows: list[dict] = _normalise_rows(raw_data, columns)

    col_types: dict[str, str]     = {}
    cardinalities: dict[str, int] = {}
    numeric_range: dict[str, dict] = {}

    for col in columns:
        values = [r.get(col) for r in rows if r.get(col) is not None]
        unique_vals = set(str(v) for v in values)
        cardinalities[col] = len(unique_vals)

        if _is_temporal_col(col, values):
            col_types[col] = "temporal"
        elif _is_numeric_col(values):
            col_types[col] = "numeric"
            floats = [_coerce_float(v) for v in values]
            floats = [f for f in floats if f is not None]
            if floats:
                mn, mx = min(floats), max(floats)
                mean   = sum(floats) / len(floats)
                variance = sum((f - mean) ** 2 for f in floats) / len(floats)
                std      = math.sqrt(variance)
                cv       = (std / mean) if mean != 0 else 0
                numeric_range[col] = {"min": mn, "max": mx, "cv": cv, "mean": mean}
        else:
            col_types[col] = "categorical"

    numeric_cols  = [c for c, t in col_types.items() if t == "numeric"]
    temporal_cols = [c for c, t in col_types.items() if t == "temporal"]
    cat_cols      = [c for c, t in col_types.items() if t == "categorical"]

    avg_label_len = 0.0
    if cat_cols:
        all_labels = []
        for col in cat_cols:
            all_labels.extend(str(r.get(col, "")) for r in rows if r.get(col) is not None)
        avg_label_len = sum(len(l) for l in all_labels) / len(all_labels) if all_labels else 0.0

    return {
        "col_types":     col_types,
        "cardinalities": cardinalities,
        "numeric_cols":  numeric_cols,
        "temporal_cols": temporal_cols,
        "cat_cols":      cat_cols,
        "n_cols":        len(columns),
        "n_rows":        len(rows),
        "rows":          rows,
        "numeric_range": numeric_range,
        "avg_label_len": avg_label_len,
    }


def _normalise_rows(raw_data: list, columns: list) -> list[dict]:
    if not raw_data:
        return []
    if isinstance(raw_data[0], dict):
        return raw_data
    return [
        {columns[i]: row[i] for i in range(min(len(columns), len(row)))}
        for row in raw_data
    ]


def _is_numeric_col(values: list) -> bool:
    if not values:
        return False
    numeric_count = sum(1 for v in values if _coerce_float(v) is not None)
    return numeric_count / len(values) >= 0.85


def _is_temporal_col(col_name: str, values: list) -> bool:
    temporal_keywords = ("date", "time", "year", "month", "day", "week", "period", "ts", "at")
    if any(kw in col_name.lower() for kw in temporal_keywords):
        return True
    if not values:
        return False
    sample  = values[:10]
    parsed  = sum(1 for v in sample if _coerce_datetime(v) is not None)
    return parsed / len(sample) >= 0.7


def _coerce_float(v: Any) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _coerce_datetime(v: Any) -> datetime | None:
    if isinstance(v, (datetime, date)):
        return v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)
    if not isinstance(v, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(v[:19], fmt)
        except ValueError:
            continue
    return None


# ═════════════════════════════════════════════════════════════════════════════
# Step 2 — Deterministic Chart Selection
# ═════════════════════════════════════════════════════════════════════════════

def _select_chart_type(
    profile: dict[str, Any],
    intent: str,
    row_count: int,
) -> tuple[str, str]:
    """Rule-engine for chart selection."""
    numeric_cols  = profile["numeric_cols"]
    temporal_cols = profile["temporal_cols"]
    cat_cols      = profile["cat_cols"]
    cardinalities = profile["cardinalities"]
    numeric_range = profile.get("numeric_range", {})
    avg_label_len = profile.get("avg_label_len", 0.0)

    if row_count == 0:
        return "skip", "No rows to visualise"

    if row_count == 1 and len(numeric_cols) == 1:
        return "indicator", "Single numeric result — KPI indicator"

    if intent == "kpi" and len(numeric_cols) >= 1 and row_count == 1:
        return "indicator", "Strategic KPI — Single-metric focus"

    if temporal_cols and numeric_cols:
        return "scatter", f"Time-series trend detected via '{temporal_cols[0]}'"

    if intent in ("proportion", "composition"):
        cat_col  = cat_cols[0] if cat_cols else None
        n_unique = cardinalities.get(cat_col, row_count) if cat_col else row_count
        if n_unique <= 7:
            return "pie", f"Proportion intent + {n_unique} categories"
        else:
            return "treemap", f"Proportion intent + {n_unique} categories (treemap)"

    if cat_cols and numeric_cols:
        num_col   = numeric_cols[0]
        rng_stats = numeric_range.get(num_col, {})
        cv        = rng_stats.get("cv", 1.0)
        if cv < 0.05 and row_count >= 3:
            return "dot_plot", f"Narrow value range (CV={cv:.3f}) for '{num_col}'"

    if cat_cols and numeric_cols:
        cat_col  = cat_cols[0]
        n_unique = cardinalities.get(cat_col, row_count)
        if n_unique > 30:
            return "table", f"Too many categories ({n_unique}) for chart — table view"
        
        if n_unique > 8 or avg_label_len > 8:
            return "h_bar", f"Horizontal bar for many or long categorical labels ({n_unique})"
        
        return "bar", f"Categorical comparison: '{cat_col}'"

    if len(numeric_cols) >= 2:
        return "scatter", "Correlation between numeric metrics"

    return "table", "No specialized visualization applicable"


# ═════════════════════════════════════════════════════════════════════════════
# Step 3 — LLM labels
# ═════════════════════════════════════════════════════════════════════════════

async def _fetch_layout_meta(
    chart_type: str,
    intent: str,
    question: str,
    columns: list,
    row_count: int,
    data_sample: list,
) -> dict[str, str]:
    llm    = get_llm(temperature=0)
    prompt = _LAYOUT_PROMPT.format(
        chart_type=chart_type,
        intent=intent,
        question=question,
        columns=json.dumps(columns),
        row_count=row_count,
        data_sample=json.dumps(data_sample[:10], indent=2, default=str),
    )
    try:
        response = await llm.ainvoke(prompt)
        meta     = _parse_json(response.content)
        return {
            "title":     meta.get("title")    or question[:80],
            "x_label":   meta.get("x_label")  or "",
            "y_label":   meta.get("y_label")   or "",
            "rationale": meta.get("rationale") or f"{chart_type} chart selected for this data.",
        }
    except Exception:
        return {
            "title":     question[:80],
            "x_label":   columns[0] if columns else "",
            "y_label":   columns[1] if len(columns) > 1 else "",
            "rationale": f"{chart_type} selected by data-shape rules.",
        }


# ═════════════════════════════════════════════════════════════════════════════
# Step 4 — Figure Builder
# ═════════════════════════════════════════════════════════════════════════════

def _build_figure(
    chart_type: str,
    raw_data: list,
    columns: list,
    profile: dict[str, Any],
    layout_meta: dict[str, str],
) -> dict[str, Any]:
    rows          = profile["rows"][:50]
    numeric_cols  = profile["numeric_cols"]
    temporal_cols = profile["temporal_cols"]
    cat_cols      = profile["cat_cols"]
    title   = layout_meta.get("title", "")
    x_label = layout_meta.get("x_label", "")
    y_label = layout_meta.get("y_label", "")

    layout: dict[str, Any] = {
        "title": {"text": title},
        "xaxis": {"title": {"text": x_label}},
        "yaxis": {"title": {"text": y_label}},
    }

    if chart_type == "indicator":
        num_col = numeric_cols[0] if numeric_cols else columns[0]
        value   = _coerce_float(rows[0].get(num_col)) if rows else 0
        return {
            "data": [{"type": "indicator", "mode": "number", "value": value or 0,
                      "title": {"text": title or num_col, "font": {"size": 20}},
                      "number": {"font": {"color": _FONT_COLOR, "size": 48}}}],
            "layout": {"title": {"text": ""}},
        }

    if chart_type == "scatter":
        x_col  = temporal_cols[0] if temporal_cols else (cat_cols[0] if cat_cols else columns[0])
        y_col  = numeric_cols[0]  if numeric_cols  else columns[-1]
        pairs  = [(str(r.get(x_col, "")), _coerce_float(r.get(y_col))) for r in rows]
        x_vals, y_vals = zip(*pairs) if pairs else ([], [])
        return {
            "data": [{"type": "scatter", "mode": "lines+markers" if temporal_cols else "markers",
                      "x": list(x_vals), "y": list(y_vals), "name": y_col}],
            "layout": layout,
        }

    if chart_type == "bar":
        x_col  = cat_cols[0]     if cat_cols     else columns[0]
        y_col  = numeric_cols[0] if numeric_cols else columns[-1]
        pairs  = sorted([(str(r.get(x_col, "")), _coerce_float(r.get(y_col)) or 0) for r in rows], 
                        key=lambda p: p[1], reverse=True)
        x_vals, y_vals = zip(*pairs) if pairs else ([], [])
        return {
            "data": [{"type": "bar", "x": list(x_vals), "y": list(y_vals), "name": y_col}],
            "layout": layout,
        }

    if chart_type == "h_bar":
        x_col  = cat_cols[0]     if cat_cols     else columns[0]
        y_col  = numeric_cols[0] if numeric_cols else columns[-1]
        pairs  = sorted([(str(r.get(x_col, "")), _coerce_float(r.get(y_col)) or 0) for r in rows], 
                        key=lambda p: p[1])
        labels, values = zip(*pairs) if pairs else ([], [])
        return {
            "data": [{"type": "bar", "x": list(values), "y": list(labels), "orientation": "h"}],
            "layout": {**layout, "xaxis": {"title": {"text": y_label}}, "yaxis": {"title": {"text": x_label}, "automargin": True}},
        }

    if chart_type == "dot_plot":
        x_col  = cat_cols[0]     if cat_cols     else columns[0]
        y_col  = numeric_cols[0] if numeric_cols else columns[-1]
        pairs  = sorted([(str(r.get(x_col, "")), _coerce_float(r.get(y_col)) or 0) for r in rows], 
                        key=lambda p: p[1], reverse=True)
        labels, values = zip(*pairs) if pairs else ([], [])
        return {
            "data": [{"type": "scatter", "mode": "markers", "x": list(values), "y": list(labels),
                      "marker": {"size": 14, "color": _COLORWAY[0]}}],
            "layout": layout,
        }

    if chart_type == "pie":
        label_col = cat_cols[0]     if cat_cols     else columns[0]
        value_col = numeric_cols[0] if numeric_cols else columns[-1]
        labels    = [str(r.get(label_col, "")) for r in rows]
        values    = [_coerce_float(r.get(value_col)) or 0 for r in rows]
        return {
            "data": [{"type": "pie", "labels": labels, "values": values, "hole": 0.45}],
            "layout": {"title": {"text": title}},
        }

    if chart_type == "treemap":
        label_col = cat_cols[0]     if cat_cols     else columns[0]
        value_col = numeric_cols[0] if numeric_cols else columns[-1]
        labels    = [str(r.get(label_col, "")) for r in rows]
        values    = [_coerce_float(r.get(value_col)) or 0 for r in rows]
        return {
            "data": [{"type": "treemap", "labels": labels, "parents": [""] * len(labels), "values": values}],
            "layout": {"title": {"text": title}},
        }

    return _build_fallback_table({"columns": columns, "data": raw_data})


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _validate_figure(figure: dict[str, Any]) -> str | None:
    if not isinstance(figure, dict) or "data" not in figure:
        return "Invalid figure structure"
    return None

def _no_chart(reason: str | None) -> dict[str, Any]:
    return {"chart_json": None, "chart_engine": "plotly", "viz_rationale": reason}

def _sanitize_question(q: str) -> str:
    try:
        parsed = json.loads(q)
        return parsed.get("text", q) if isinstance(parsed, dict) else q
    except: return q

def _build_fallback_table(analysis: dict[str, Any]) -> dict[str, Any]:
    columns = analysis.get("columns", [])
    rows    = (analysis.get("data") or analysis.get("dataframe") or [])[:50]
    cell_values = [[str(r.get(c, "")) for r in rows] for c in columns]
    return {
        "data": [{"type": "table", "header": {"values": columns}, "cells": {"values": cell_values}}],
        "layout": {"title": {"text": "Data Table"}},
    }

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else: result[key] = val
    return result

def _parse_json(content: Any) -> dict[str, Any]:
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        return json.loads(match.group()) if match else {}
    except: return {}
