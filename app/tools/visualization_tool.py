from app.services.llm_service import llm_service
from app.prompts import VISUALIZATION_PROMPT
from app.core.logging import get_logger

import plotly.express as px
import pandas as pd
import json

logger = get_logger(__name__)


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that are numeric (int or float)."""
    return df.select_dtypes(include=["number"]).columns.tolist()


def _date_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that are datetime or look like dates."""
    date_cols = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()
    # Also catch string columns that pandas hasn't parsed yet
    for col in df.select_dtypes(include=["object"]).columns:
        sample = df[col].dropna().head(5)
        try:
            pd.to_datetime(sample)
            date_cols.append(col)
        except Exception:
            pass
    return date_cols


def _column_type_summary(df: pd.DataFrame) -> str:
    """Build a human-readable column list with types for the prompt."""
    parts = []
    numeric = set(_numeric_columns(df))
    date = set(_date_columns(df))
    for col in df.columns:
        if col in date:
            parts.append(f"{col} (date)")
        elif col in numeric:
            parts.append(f"{col} (numeric)")
        else:
            parts.append(f"{col} (categorical)")
    return ", ".join(parts)


def _safe_config(config: dict, df: pd.DataFrame, query: str) -> dict:
    """
    Validate and repair the LLM's chart config:
    - Ensure x and y are real column names.
    - Ensure y is numeric. If not, swap to the first numeric column.
    - Auto-detect chart type from x column type when the LLM picks wrong.
    """
    columns = list(df.columns)
    numeric = _numeric_columns(df)
    date_cols = _date_columns(df)

    chart = config.get("chart", "bar")
    x = config.get("x")
    y = config.get("y")

    # ── Validate x ──────────────────────────────────────────────────────────
    if x not in columns:
        # Prefer a date column; fall back to first column
        x = date_cols[0] if date_cols else columns[0]

    # ── Validate y — must be numeric ────────────────────────────────────────
    if y not in columns or y not in numeric:
        # Pick the first numeric column that isn't x
        candidates = [c for c in numeric if c != x]
        if candidates:
            y = candidates[0]
        elif numeric:
            y = numeric[0]
        else:
            # No numeric columns at all — fall back to second column
            y = columns[1] if len(columns) > 1 else columns[0]
        logger.warning(f"LLM chose non-numeric y; corrected to '{y}'")

    # ── Auto-correct chart type ──────────────────────────────────────────────
    if x in date_cols and chart != "line":
        chart = "line"
    elif x not in date_cols and x not in numeric and chart == "line":
        chart = "bar"

    return {"chart": chart, "x": x, "y": y}


async def choose_chart(df: pd.DataFrame, query: str) -> dict:
    prompt = VISUALIZATION_PROMPT.format(
        columns=_column_type_summary(df),
        query=query,
    )

    result = await llm_service.generate([
        {"role": "user", "content": prompt}
    ])

    raw = result["text"].strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    try:
        config = json.loads(raw)
    except Exception:
        logger.warning(f"Visualization LLM returned unparseable output: {raw[:200]!r}")
        config = {}

    return _safe_config(config, df, query)


async def run_visualization(df: pd.DataFrame, action: str, query: str):
    if df.empty:
        return {"error": "Empty dataset"}

    config = await choose_chart(df, query)

    x = config["x"]
    y = config["y"]
    chart = config["chart"]

    logger.info(f"Rendering {chart} chart: x={x!r}, y={y!r}")

    try:
        if chart == "bar":
            fig = px.bar(df, x=x, y=y, title=f"{y} by {x}")
        elif chart == "scatter":
            fig = px.scatter(df, x=x, y=y, title=f"{y} vs {x}")
        else:  # line (default)
            fig = px.line(df, x=x, y=y, title=f"{y} over {x}")
    except Exception as e:
        logger.error(f"Plotly failed with config {config}: {e}")
        # Last-resort fallback: first two columns
        fig = px.line(df, x=df.columns[0], y=df.columns[1])

    return fig.to_json()