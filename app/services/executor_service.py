from app.tools.etl_tool import run_etl
from app.tools.analytics_tool import run_analytics
from app.tools.visualization_tool import run_visualization
from app.core.logging import get_logger

logger = get_logger(__name__)

PRIORITY_MAP = {
    "auto": ["analytics", "visualization", "etl"],
    "analytics": ["analytics", "visualization", "etl"],
    "visualization": ["visualization", "analytics", "etl"],
    "etl": ["etl", "analytics", "visualization"],
}


class ExecutorService:

    async def execute(self, plan, df, mode: str, query: str, stream_callback=None):
        if plan is None:
            raise ValueError("No plan provided to executor")

        priority = PRIORITY_MAP.get(mode, PRIORITY_MAP["auto"])

        steps = sorted(
            plan.get("steps", []),
            key=lambda x: priority.index(x["tool"]) if x["tool"] in priority else 999,
        )

        if not steps:
            raise ValueError("Plan contains no steps")

        result = None
        current_df = df  # work on a local copy so original state is not mutated

        for step in steps:
            tool = step.get("tool")
            action = step.get("action", "")

            if stream_callback:
                await stream_callback(f"Running {tool}: {action}")

            if tool == "etl":
                if current_df is None:
                    raise ValueError("ETL step requires a dataset but none was provided")
                current_df = run_etl(current_df, action)

            elif tool == "analytics":
                if current_df is None:
                    raise ValueError("Analytics step requires a dataset but none was provided")
                current_df = run_analytics(current_df, action)

            elif tool == "visualization":
                if current_df is None:
                    raise ValueError("Visualization step requires a dataset but none was provided")
                result = await run_visualization(current_df, action, query)

            else:
                logger.warning(f"Unknown tool in plan step: {tool!r} — skipping")

        if result is not None:
            return result

        # Fallback: return a structured, frontend-friendly dict instead of raw df.to_dict()
        if current_df is not None:
            return {
                "summary": {
                    "rows": len(current_df),
                    "columns": list(current_df.columns),
                },
                "data": current_df.head(20).to_dict(orient="records"),
            }

        raise ValueError("Execution produced no result and no dataframe to return")


executor_service = ExecutorService()