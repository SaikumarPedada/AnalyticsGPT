from app.services.llm_service import llm_service
from app.core.logging import get_logger

logger = get_logger(__name__)

_VALID_MODES = {"analytics", "visualization", "etl"}


class RouterService:

    async def route(self, message: str, mode: str | None) -> str:
        # If the user or caller already picked a non-auto mode, honour it
        if mode and mode != "auto":
            return mode

        prompt = (
            "Classify the following user request into exactly one category.\n"
            "Categories: analytics, visualization, etl\n\n"
            "Rules:\n"
            "- analytics: aggregation, statistics, groupby, summary, trends, correlation\n"
            "- visualization: chart, plot, graph, show, draw, visualize\n"
            "- etl: clean, filter, remove, fill, transform, sort, deduplicate\n\n"
            f"User request: {message}\n\n"
            "Reply with ONE word only — analytics, visualization, or etl."
        )

        try:
            result = await llm_service.generate([
                {"role": "user", "content": prompt}
            ])

            # Extract the first word and normalise
            raw = result["text"].strip().lower()
            # Drop markdown fences or trailing punctuation
            first_word = raw.split()[0].strip("`.,:;!?\"'") if raw.split() else ""

            if first_word in _VALID_MODES:
                logger.info(f"Router classified '{message[:60]}' → {first_word}")
                return first_word

            # Fallback: scan the full response for any valid mode keyword
            for word in raw.split():
                cleaned = word.strip("`.,:;!?\"'")
                if cleaned in _VALID_MODES:
                    logger.info(f"Router fallback scan → {cleaned}")
                    return cleaned

        except Exception as e:
            logger.warning(f"Router LLM call failed: {e}")

        # Safe default
        logger.warning(f"Router could not classify message, defaulting to 'analytics'")
        return "analytics"


router_service = RouterService()