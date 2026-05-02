from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional, List


class Settings(BaseSettings):
    # App
    APP_NAME: str = "AnalyticsGPT"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    API_KEY: str = "change-me"

    # JWT Auth
    JWT_SECRET_KEY: str = "change-me-to-a-long-random-secret-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost/qwenchat"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://user:pass@localhost/qwenchat"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_COLLECTION: str = "chat_memories"
    QDRANT_VECTOR_SIZE: int = 384

    # LLM (Qwen 2.5 7B Instruct via llama.cpp)
    MODEL_BASE_PATH: str = "/models"
    QWEN_MODEL_PATH: str = "/models/qwen"
    LLM_CTX_SIZE: int = 120000
    LLM_THREADS: int = 8
    LLM_GPU_LAYERS: int = 0
    LLM_MAX_TOKENS: int = 4096  
    LLM_TEMPERATURE: float = 0.7
    LLM_TOP_P: float = 0.9
    LLM_REPEAT_PENALTY: float = 1.1

    # Embeddings (BGE-small)
    BGE_MODEL_PATH: str = "/models/bge-small-en"
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en"
    TOKENIZER_NAME: str = "Qwen/Qwen2.5-7B-Instruct"

    # Cache
    CACHE_TYPE: str = "memory"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # Session / MCP
    MCP_HISTORY_LIMIT: int = 10
    MCP_SAVE_BATCH_SIZE: int = 100
    SESSION_IDLE_TIMEOUT_MINUTES: int = 60

    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = 30

    # Rate limiting
    MAX_CONCURRENT_REQUESTS: int = 5
    REQUEST_TIMEOUT: int = 60

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()