import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from typing import Optional

router = APIRouter(prefix="/dataset", tags=["dataset"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

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
):
    """
    Upload a CSV / Excel dataset.

    Auth is OPTIONAL here so the frontend can upload before a session token
    is ready, or during a quick demo without login.

    To make auth required: swap `get_optional_user_id` → `get_current_user_id`
    and change the type annotation to `int`.
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

    # UUID filename — prevents path traversal
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)

    with open(file_path, "wb") as f:
        f.write(content)

    return {
        "file_path": file_path,
        "original_filename": file.filename,
        "user_id": user_id,  
    }