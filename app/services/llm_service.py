import httpx
import asyncio
from typing import List, Dict, Optional
from app.core.config import get_settings
from app.core.logging import get_logger
from app.prompts import SYSTEM_PROMPT

settings = get_settings()
logger = get_logger(__name__)

ALLOWED_MODELS = {"openai/gpt-oss-120b", "qwen/qwen3.6-27b"}


class LLMService:
    def __init__(self):
        # Kept for compatibility / health checks
        self.llm = "groq"
        self.tokenizer = "groq"

    def load_model(self) -> None:
        # No-op with API
        pass

    def load_tokenizer(self) -> None:
        # No-op with API
        pass

    def estimate_tokens(self, text: str) -> int:
        # Simple word/character estimation as a fallback: ~4 characters per token
        return len(text) // 4

    async def generate(self, messages: List[Dict], model: Optional[str] = None) -> Dict:
        model = model or settings.GROQ_DEFAULT_MODEL
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model {model!r} is not allowed. Must be one of {list(ALLOWED_MODELS)}")

        if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "change-me":
            raise ValueError("GROQ_API_KEY is not configured")

        # Prepends system prompt if not present
        payload_messages = []
        if not any(msg.get("role") == "system" for msg in messages):
            payload_messages.append({"role": "system", "content": SYSTEM_PROMPT})
        payload_messages.extend(messages)

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": payload_messages,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "temperature": settings.LLM_TEMPERATURE,
            "top_p": settings.LLM_TOP_P,
        }

        logger.info(f"Sending request to Groq API (model={model})")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=data)
            if response.status_code != 200:
                logger.error(f"Groq API error (status={response.status_code}): {response.text}")
                response.raise_for_status()

            res_json = response.json()
            response_text = res_json["choices"][0]["message"]["content"].strip()
            usage = res_json.get("usage", {})
            tokens = usage.get("total_tokens") or (
                self.estimate_tokens(response_text)
            )

            return {"text": response_text, "tokens": tokens}

    def generate_sync(self, messages: List[Dict], model: Optional[str] = None) -> Dict:
        """Synchronous version for startup warmup/test before loop is running."""
        model = model or settings.GROQ_DEFAULT_MODEL
        if model not in ALLOWED_MODELS:
            raise ValueError(f"Model {model!r} is not allowed. Must be one of {list(ALLOWED_MODELS)}")

        if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "change-me":
            raise ValueError("GROQ_API_KEY is not configured")

        payload_messages = []
        if not any(msg.get("role") == "system" for msg in messages):
            payload_messages.append({"role": "system", "content": SYSTEM_PROMPT})
        payload_messages.extend(messages)

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "model": model,
            "messages": payload_messages,
            "max_tokens": settings.LLM_MAX_TOKENS,
            "temperature": settings.LLM_TEMPERATURE,
            "top_p": settings.LLM_TOP_P,
        }

        logger.info(f"Sending sync request to Groq API (model={model})")

        with httpx.Client(timeout=60.0) as client:
            response = client.post(url, headers=headers, json=data)
            if response.status_code != 200:
                logger.error(f"Groq API error (status={response.status_code}): {response.text}")
                response.raise_for_status()

            res_json = response.json()
            response_text = res_json["choices"][0]["message"]["content"].strip()
            usage = res_json.get("usage", {})
            tokens = usage.get("total_tokens") or (
                self.estimate_tokens(response_text)
            )

            return {"text": response_text, "tokens": tokens}


llm_service = LLMService()
