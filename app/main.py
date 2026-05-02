from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import setup_logging, get_logger
from app.services.llm_service import llm_service
from app.services.embedding_service import embedding_service
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.dataset import router as dataset_router

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    logger.info("=== Starting AnalyticsGPT-Copilot backend ===")

    try:
        logger.info("Loading LLM model…")
        llm_service.load_model()
        logger.info("Loading tokenizer…")
        llm_service.load_tokenizer()
        logger.info("Running LLM warmup…")
        llm_service.generate_sync([{"role": "user", "content": "Hello"}])
        logger.info("LLM ready")
    except Exception as e:
        logger.exception("Failed to load LLM")
        raise e

    try:
        logger.info("Loading embedding model…")
        embedding_service.load_model()
        logger.info("Embedding model ready")
    except Exception as e:
        logger.exception("Failed to load embedding model")
        raise e

    logger.info("=== System fully ready ===")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("Shutting down…")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(health_router)
app.include_router(dataset_router)

@app.get("/")
def root():
    return {"app": settings.APP_NAME, "env": settings.APP_ENV, "version": "1.0.0"}
