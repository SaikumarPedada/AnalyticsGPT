import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict
from app.core.config import get_settings
from app.core.logging import get_logger
from app.prompts import SYSTEM_PROMPT

settings = get_settings()
logger = get_logger(__name__)

# Single thread pool for blocking llama.cpp inference
_executor = ThreadPoolExecutor(max_workers=1)


class LLMService:
    def __init__(self):
        self.llm = None
        self.tokenizer = None

    # ── Loading ───────────────────────────────────────────────────────────────
    def load_model(self) -> None:
        if self.llm:
            return
        from llama_cpp import Llama

        model_dir = settings.QWEN_MODEL_PATH
        if not os.path.exists(model_dir):
            raise RuntimeError(f"Qwen model directory not found: {model_dir}")

        gguf_files = [
            os.path.join(model_dir, f)
            for f in sorted(os.listdir(model_dir))
            if f.endswith(".gguf")
        ]
        if not gguf_files:
            raise RuntimeError(f"No .gguf files in: {model_dir}")

        model_path = gguf_files[0]
        logger.info(f"Loading GGUF model: {model_path}")

        self.llm = Llama(
            model_path=model_path,
            n_ctx=settings.LLM_CTX_SIZE,
            n_threads=settings.LLM_THREADS,
            n_gpu_layers=settings.LLM_GPU_LAYERS,
            verbose=False,
        )
        logger.info("GGUF model loaded")

    def load_tokenizer(self) -> None:
        if self.tokenizer:
            return
        from transformers import AutoTokenizer

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                settings.TOKENIZER_NAME,
                trust_remote_code=True,
                local_files_only=True,
            )
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(
                settings.TOKENIZER_NAME,
                trust_remote_code=True,
            )
        logger.info("Tokenizer loaded")

    # ── Prompt formatting (Qwen 2.5 ChatML) ──────────────────────────────────
    def format_messages(self, messages: List[Dict]) -> str:
        """
        Qwen 2.5 uses ChatML format:
          <|im_start|>system\n...\n<|im_end|>
          <|im_start|>user\n...\n<|im_end|>
          <|im_start|>assistant\n
        """
        prompt = f"<|im_start|>system\n{SYSTEM_PROMPT}\n<|im_end|>\n"
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            prompt += f"<|im_start|>{role}\n{content}\n<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"
        return prompt

    # ── Token estimation ──────────────────────────────────────────────────────
    def estimate_tokens(self, text: str) -> int:
        self.load_tokenizer()
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    # ── Synchronous generation (runs in thread pool) ──────────────────────────
    def _generate_sync(self, messages: List[Dict]) -> Dict:
        self.load_model()
        self.load_tokenizer()

        prompt = self.format_messages(messages)

        output = self.llm(
            prompt,
            max_tokens=settings.LLM_MAX_TOKENS,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            repeat_penalty=settings.LLM_REPEAT_PENALTY,
            stop=["<|im_end|>", "<|endoftext|>"],
        )

        response_text = output["choices"][0]["text"].strip()

        # Use llama.cpp usage if available, else estimate
        usage = output.get("usage", {})
        tokens = usage.get("total_tokens") or (
            self.estimate_tokens(prompt) + self.estimate_tokens(response_text)
        )

        return {"text": response_text, "tokens": tokens}

    # ── Async wrapper ──────────────────────────────────────────────────────────
    async def generate(self, messages: List[Dict]) -> Dict:
        """Non-blocking async wrapper around the synchronous llama.cpp call."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._generate_sync, messages)

    def generate_sync(self, messages: List[Dict]) -> Dict:
        """Kept for startup warmup (called before event loop)."""
        return self._generate_sync(messages)


llm_service = LLMService()
