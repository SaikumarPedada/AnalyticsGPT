from fastapi import APIRouter, Depends
from app.services.cache_service import cache
from app.services.qdrant_service import qdrant_service
from app.services.llm_service import llm_service
from app.core.security import verify_api_key

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
async def health():
    """Public liveness probe."""
    return {"status": "ok"}


@router.get("/ready", dependencies=[Depends(verify_api_key)])
async def readiness():
    """Detailed readiness — checks all subsystems."""
    return {
        "llm": llm_service.llm is not None,
        "tokenizer": llm_service.tokenizer is not None,
        "qdrant": qdrant_service.health(),
        "active_sessions": cache.active_count(),
    }
