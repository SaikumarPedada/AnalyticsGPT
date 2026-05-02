from app.services.llm_service import llm_service
from app.prompts import EXPLANATION_PROMPT
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExplanationService:

    async def generate(self, message: str, steps: list) -> str:
        if not steps:
            return ""

        steps_text = "\n".join(
            f"{i + 1}. {s['tool']} → {s['action']}"
            for i, s in enumerate(steps)
        )

        prompt = EXPLANATION_PROMPT.format(
            message=message,
            steps=steps_text,
        )

        try:
            result = await llm_service.generate([
                {"role": "user", "content": prompt}
            ])

            text = result["text"].strip()

            # Strip markdown fences if the model wrapped its answer
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                ).strip()

            return text

        except Exception as e:
            logger.warning(f"Explanation generation failed: {e}")
            return ""


explanation_service = ExplanationService()