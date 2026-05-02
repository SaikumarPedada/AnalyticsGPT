import json
from typing import Dict
from app.services.llm_service import llm_service
from app.core.logging import get_logger
from app.prompts import PLANNER_PROMPT

logger = get_logger(__name__)


class PlannerService:

    async def create_plan(self, db, user_id: int, message: str, mode: str, schema: str) -> Dict:
        prompt = PLANNER_PROMPT.format(
            message=message,
            mode=mode,
            schema=schema,
        )

        try:
            result = await llm_service.generate([
                {"role": "user", "content": prompt}
            ])

            return json.loads(result["text"])

        except Exception as e:
            logger.warning(f"Planner failed, mode-aware fallback used: {e}")

            # Mode-aware safe fallback — preserves user intent when the LLM planner fails
            if mode == "visualization":
                return {"steps": [{"tool": "visualization", "action": "chart"}]}
            elif mode == "etl":
                return {"steps": [{"tool": "etl", "action": "remove_null"}]}
            else:
                # analytics or auto
                return {"steps": [{"tool": "analytics", "action": "summary"}]}


planner_service = PlannerService()