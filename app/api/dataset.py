import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import Dataset

router = APIRouter(prefix="/dataset", tags=["dataset"])

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

_optional_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def get_optional_user_id(token: Optional[str] = Depends(_optional_oauth2)) -> Optional[int]:
    """Resolve user_id from Bearer token when present; return None otherwise."""
    if not token:
        return None
    try:
        from app.core.security import decode_token
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        sub = payload.get("sub")
        return int(sub) if sub else None
    except Exception:
        return None


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a CSV / Excel dataset directly to the database.

    Auth is OPTIONAL here so the frontend can upload before a session token
    is ready, or during a quick demo without login.
    """
    # Validate extension
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read content and enforce size limit
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB",
        )

    # Store dataset directly in the database
    dataset_id = str(uuid.uuid4())
    db_dataset = Dataset(
        dataset_id=dataset_id,
        filename=file.filename or "dataset",
        content=content,
    )
    
    db.add(db_dataset)
    await db.commit()

    return {
        "file_path": dataset_id,  # return UUID in file_path field for compatibility
        "original_filename": file.filename,
        "user_id": user_id,  
    }