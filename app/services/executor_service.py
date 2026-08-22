import pandas as pd
import numpy as np
import plotly.express as px
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExecutorService:

    async def execute(self, plan, df, mode: str, query: str, stream_callback=None, model: str | None = None):
        if plan is None:
            raise ValueError("No plan provided to executor")

        code = plan.get("code")
        is_visualization = plan.get("is_visualization", False)

        if not code:
            raise ValueError("Plan contains no executable code")

        if stream_callback:
            await stream_callback("Executing dynamic Python/Pandas analysis...")

        # Setup local scope for execution
        local_scope = {
            "df": df.copy() if df is not None else None,
            "pd": pd,
            "np": np,
            "px": px,
            "fig": None,
        }

        # Run python code
        try:
            logger.info("Executing generated python script")
            compiled_code = compile(code, "<string>", "exec")
            exec(compiled_code, globals(), local_scope)
        except Exception as e:
            logger.exception("Dynamic code execution failed")
            raise e

        # If it was visualization, extract 'fig' and return plotly json
        if is_visualization:
            fig = local_scope.get("fig")
            if fig is None:
                raise ValueError("Code finished but did not define the expected 'fig' Plotly Figure variable.")
            
            return fig.to_json()

        # Otherwise, extract 'df' and return formatted data
        updated_df = local_scope.get("df")
        if updated_df is None:
            raise ValueError("Code finished but 'df' is None or was deleted.")

        if isinstance(updated_df, pd.Series):
            updated_df = updated_df.to_frame()

        if isinstance(updated_df, pd.DataFrame):
            return {
                "summary": {
                    "rows": len(updated_df),
                    "columns": list(updated_df.columns),
                },
                "data": updated_df.head(20).to_dict(orient="records"),
            }

        # If the code returned something else, return it directly
        return updated_df


executor_service = ExecutorService()