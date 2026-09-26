from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timedelta, timezone
import hashlib

from app.models import User, RefreshToken
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshRequest, UserOut
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user_id,
)
from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
logger = get_logger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    # Check username uniqueness
    if await User.filter(username=payload.username).exists():
        raise HTTPException(status_code=409, detail="Username already taken")

    # Check email uniqueness
    if await User.filter(email=payload.email).exists():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await User.create(
        username=payload.username,
        email=payload.email,
        password=hash_password(payload.password),
    )
    logger.info(f"New user registered: {user.username} ({user.email})")
    return {"message": "Account created", "user_id": user.user_id}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    user = await User.get_or_none(email=payload.email)

    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Issue tokens
    token_data = {"sub": str(user.user_id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Store refresh token hash
    await RefreshToken.create(
        user_id=user.user_id,
        token_hash=_hash_token(refresh_token),
        expires_at=_now_utc() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )

    # Update last_login
    user.last_login = _now_utc()
    await user.save()

    logger.info(f"User logged in: {user.username}")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user_id=user.user_id,
        username=user.username,
        email=user.email,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    decoded = decode_token(payload.refresh_token)
    if decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    token_hash = _hash_token(payload.refresh_token)
    stored = await RefreshToken.get_or_none(
        token_hash=token_hash,
        revoked=False,
    )
    
    if not stored:
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")

    expires_at = stored.expires_at.replace(tzinfo=timezone.utc) if stored.expires_at.tzinfo is None else stored.expires_at
    if expires_at < _now_utc():
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")

    user_id = int(decoded["sub"])
    user = await User.get_or_none(user_id=user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    # Rotate: revoke old, issue new
    stored.revoked = True
    await stored.save()

    token_data = {"sub": str(user_id)}
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)

    await RefreshToken.create(
        user_id=user_id,
        token_hash=_hash_token(new_refresh),
        expires_at=_now_utc() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user_id=user.user_id,
        username=user.username,
        email=user.email,
    )


@router.post("/logout")
async def logout(payload: RefreshRequest):
    token_hash = _hash_token(payload.refresh_token)
    stored = await RefreshToken.get_or_none(token_hash=token_hash)
    if stored:
        stored.revoked = True
        await stored.save()
    return {"message": "Logged out"}


@router.get("/me", response_model=UserOut)
async def me(user_id: int = Depends(get_current_user_id)):
    user = await User.get_or_none(user_id=user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
