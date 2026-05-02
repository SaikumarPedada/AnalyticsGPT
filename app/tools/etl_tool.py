import pandas as pd
from app.core.logging import get_logger

logger = get_logger(__name__)


def run_etl(df: pd.DataFrame, action: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise ValueError("Invalid dataframe")

    action = action.lower().strip()

    # ── remove_null / dropna ─────────────────────────────────────────────────
    if "remove_null" in action or "dropna" in action:
        result = df.dropna()
        logger.info(f"ETL remove_null: {len(df)} → {len(result)} rows")
        return result

    # ── fill_null / fillna ───────────────────────────────────────────────────
    if "fill_null" in action or "fillna" in action:
        # Fill numeric cols with 0, string cols with empty string
        result = df.copy()
        for col in result.columns:
            if result[col].dtype in ["float64", "int64", "float32", "int32"]:
                result[col] = result[col].fillna(0)
            else:
                result[col] = result[col].fillna("")
        return result

    # ── dedup / drop_duplicates ───────────────────────────────────────────────
    if "dedup" in action or "duplicate" in action:
        result = df.drop_duplicates()
        logger.info(f"ETL dedup: {len(df)} → {len(result)} rows")
        return result

    # ── sort_<column> or sort_by_<column> ────────────────────────────────────
    if "sort" in action:
        # Accept: "sort_sales", "sort_by_sales", "sort_sales_desc"
        descending = "desc" in action
        parts = action.replace("sort_by_", "").replace("sort_", "").split("_")
        col_candidates = [p for p in parts if p not in ("asc", "desc", "sort", "by")]
        col = col_candidates[0] if col_candidates else ""
        if col and col in df.columns:
            return df.sort_values(col, ascending=not descending).reset_index(drop=True)
        else:
            logger.warning(f"ETL sort: column '{col}' not found")
        return df

    # ── filter_<column>_gt_<value> / filter_<column>_lt_<value> ─────────────
    if "filter" in action:
        # Patterns:  filter_sales_gt_100   filter_age_lt_30   filter_region_eq_west
        try:
            parts = action.split("_")
            # find operator index
            op_map = {"gt": ">", "lt": "<", "gte": ">=", "lte": "<=", "eq": "==", "ne": "!="}
            op_idx = next((i for i, p in enumerate(parts) if p in op_map), None)

            if op_idx is None or op_idx < 2:
                raise ValueError(f"Cannot parse filter action: {action!r}")

            col = "_".join(parts[1:op_idx])       # supports multi-word column names
            op = op_map[parts[op_idx]]
            val_str = "_".join(parts[op_idx + 1:])

            if col not in df.columns:
                raise ValueError(f"Column '{col}' not in dataframe")

            # Try numeric first, then string comparison
            try:
                val = float(val_str)
                result = df.query(f"`{col}` {op} @val")
            except ValueError:
                val = val_str
                result = df[df[col].astype(str).str.lower().apply(
                    lambda x: eval(f"x {op} val.lower()", {"x": x, "val": val})
                )]

            logger.info(f"ETL filter `{col}` {op} {val_str!r}: {len(df)} → {len(result)} rows")
            return result

        except Exception as e:
            logger.warning(f"ETL filter failed ({e}), returning df unchanged")
            return df

    # ── parse_dates_<column> ─────────────────────────────────────────────────
    if "parse_date" in action or "to_date" in action:
        parts = action.split("_")
        col = parts[-1] if len(parts) > 1 else ""
        if col and col in df.columns:
            try:
                df = df.copy()
                df[col] = pd.to_datetime(df[col], infer_datetime_format=True)
                logger.info(f"ETL parse_dates: column '{col}' converted to datetime")
            except Exception as e:
                logger.warning(f"ETL parse_dates on '{col}' failed: {e}")
        else:
            logger.warning(f"ETL parse_dates: column '{col}' not found")
        return df

    # ── unknown action ────────────────────────────────────────────────────────
    logger.warning(f"Unknown ETL action: '{action}' — returning dataframe unchanged")
    return df