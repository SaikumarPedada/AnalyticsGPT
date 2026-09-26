import httpx
import asyncio
import json
from typing import List, Dict, Optional, Any
from app.core.config import get_settings
from app.core.logging import get_logger
from app.prompts import SYSTEM_PROMPT

settings = get_settings()
logger = get_logger(__name__)

ALLOWED_MODELS = {"openai/gpt-oss-120b", "qwen/qwen3.6-27b"}


class LLMService:
    def __init__(self):
        self.llm = "groq"
        self.tokenizer = "groq"

    def load_model(self) -> None:
        pass

    def load_tokenizer(self) -> None:
        pass

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def get_mcp_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Export OpenAI-compatible tool schemas for Groq API from app.mcp_server.
        """
        try:
            from app.mcp_server import mcp_server
            tools_schema = []
            
            # Map tools registered in FastMCP instance
            for name, func in getattr(mcp_server, "_tools", {}).items():
                doc = func.__doc__ or "Execute MCP tool"
                tools_schema.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": doc.strip(),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                })
            return tools_schema
        except Exception as e:
            logger.warning(f"Could not load MCP tools schema: {e}")
            return []

    async def execute_mcp_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute an MCP tool function by name with parsed arguments.
        """
        from app.mcp_server import mcp_server
        tools = getattr(mcp_server, "_tools", {})
        func = tools.get(name)
        if not func:
            return f"Error: MCP tool '{name}' not found."
        
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(**arguments)
            else:
                return func(**arguments)
        except Exception as e:
            logger.error(f"Error executing MCP tool '{name}': {e}")
            return f"Error executing tool '{name}': {e}"

    async def generate(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None
    ) -> Dict:
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

        if tools:
            data["tools"] = tools

        logger.info(f"Sending request to Groq API (model={model})")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=data)
            if response.status_code != 200:
                logger.error(f"Groq API error (status={response.status_code}): {response.text}")
                response.raise_for_status()

            res_json = response.json()
            choice = res_json["choices"][0]["message"]
            response_text = (choice.get("content") or "").strip()
            tool_calls = choice.get("tool_calls")

            usage = res_json.get("usage", {})
            tokens = usage.get("total_tokens") or self.estimate_tokens(response_text)

            return {
                "text": response_text,
                "tokens": tokens,
                "tool_calls": tool_calls,
            }

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
            response_text = (res_json["choices"][0]["message"].get("content") or "").strip()
            usage = res_json.get("usage", {})
            tokens = usage.get("total_tokens") or self.estimate_tokens(response_text)

            return {"text": response_text, "tokens": tokens}


llm_service = LLMService()
