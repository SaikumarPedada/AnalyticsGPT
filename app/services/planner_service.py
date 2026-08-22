import json
from typing import Dict
from app.services.llm_service import llm_service
from app.core.logging import get_logger
from app.prompts import PLANNER_PROMPT

logger = get_logger(__name__)


class PlannerService:

    async def create_plan(self, db, user_id: int, message: str, mode: str, schema: str, model: str | None = None) -> Dict:
        prompt = PLANNER_PROMPT.format(
            message=message,
            schema=schema,
        )

        try:
            result = await llm_service.generate(
                [{"role": "user", "content": prompt}],
                model=model
            )

            raw = result["text"].strip()
            # Strip markdown fences if the model wrapped its JSON answer
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                ).strip()

            return json.loads(raw)

        except Exception as e:
            logger.warning(f"Planner failed, mode-aware fallback used: {e}")

            # Mode-aware safe fallback — preserves user intent when the LLM planner fails
            if mode == "visualization":
                return {
                    "code": "import plotly.express as px\nfig = px.line(df, x=df.columns[0], y=df.columns[1])",
                    "is_visualization": True
                }
            else:
                return {
                    "code": "df = df.describe(include='all').reset_index().rename(columns={'stat': 'stat'})",
                    "is_visualization": False
                }


planner_service = PlannerService()