from fastapi import APIRouter, Depends
from app.core.config import get_settings
from app.services.cache_service import cache
from app.services.qdrant_service import qdrant_service
from app.core.security import verify_api_key

router = APIRouter(prefix="/health", tags=["health"])
settings = get_settings()


@router.get("/")
async def health():
    """Public liveness probe."""
    return {"status": "ok"}


@router.get("/ready", dependencies=[Depends(verify_api_key)])
async def readiness():
    """Detailed readiness — checks all subsystems."""
    return {
        "llm": bool(settings.GROQ_API_KEY and settings.GROQ_API_KEY not in ("change-me", "your_groq_api_key_here")),
        "qdrant": qdrant_service.health(),
        "active_sessions": cache.active_count(),
    }
