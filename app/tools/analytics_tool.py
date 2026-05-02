import pandas as pd
from app.core.logging import get_logger

logger = get_logger(__name__)


def run_analytics(df: pd.DataFrame, action: str) -> pd.DataFrame:
    if df.empty:
        return df

    action = action.lower().strip()

    # ── groupby_<column> ──────────────────────────────────────────────────────
    if "groupby" in action:
        # Support both "groupby_region" and "groupby region"
        parts = action.replace("groupby_", "").replace("groupby ", "").strip().split()
        col = parts[0] if parts else ""
        if col and col in df.columns:
            try:
                return df.groupby(col).sum(numeric_only=True).reset_index()
            except Exception as e:
                logger.warning(f"groupby on '{col}' failed: {e}")
        else:
            logger.warning(f"groupby column '{col}' not found in {list(df.columns)}")
        return df

    # ── mean ─────────────────────────────────────────────────────────────────
    if "mean" in action:
        return (
            df.mean(numeric_only=True)
            .to_frame(name="mean")
            .reset_index()
            .rename(columns={"index": "column"})
        )

    # ── sum ──────────────────────────────────────────────────────────────────
    if "sum" in action:
        return (
            df.sum(numeric_only=True)
            .to_frame(name="sum")
            .reset_index()
            .rename(columns={"index": "column"})
        )

    # ── count ─────────────────────────────────────────────────────────────────
    if "count" in action:
        return (
            df.count()
            .to_frame(name="count")
            .reset_index()
            .rename(columns={"index": "column"})
        )

    # ── summary / describe ───────────────────────────────────────────────────
    if "summary" in action or "describe" in action:
        # describe() returns a DataFrame with a float index — reset so the
        # executor's structured formatter can serialise it cleanly
        return df.describe(include="all").reset_index().rename(columns={"index": "stat"})

    # ── correlation ──────────────────────────────────────────────────────────
    if "corr" in action:
        return df.select_dtypes(include="number").corr().reset_index()

    # ── unknown action — return df unchanged with a warning ──────────────────
    logger.warning(f"Unknown analytics action: '{action}' — returning dataframe unchanged")
    return df