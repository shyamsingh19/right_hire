from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key, get_current_user, hash_api_key
from app.config import settings
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory sliding-window limiter for /auth/signup — the one unauthenticated,
# free-to-call endpoint, so it's the obvious target for API-key farming. Per-process
# only (fine for a single-worker MVP); a multi-process deploy needs a shared store.
_SIGNUP_WINDOW_SECONDS = 3600
_SIGNUP_MAX_PER_WINDOW = 5
_signup_attempts: dict[str, list[float]] = defaultdict(list)


def _check_signup_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    attempts = _signup_attempts[client_ip]
    attempts[:] = [t for t in attempts if now - t < _SIGNUP_WINDOW_SECONDS]
    if len(attempts) >= _SIGNUP_MAX_PER_WINDOW:
        raise HTTPException(
            status_code=429, detail="Too many signups from this address — try again later"
        )
    attempts.append(now)


class SignupRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _looks_like_email(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v


class SignupResponse(BaseModel):
    user_id: str
    email: str
    api_key: str  # shown once — only the hash is stored server-side
    credits: int


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)):
    _check_signup_rate_limit(request.client.host if request.client else "unknown")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    api_key = generate_api_key()
    user = User(
        email=body.email,
        api_key_hash=hash_api_key(api_key),
        credits=settings.signup_free_credits,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return SignupResponse(user_id=user.id, email=user.email, api_key=api_key, credits=user.credits)


class RotateKeyResponse(BaseModel):
    api_key: str  # new key — shown once; the old key stops working immediately


@router.post("/rotate-key", response_model=RotateKeyResponse)
async def rotate_key(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Issue a new API key for the caller, invalidating the current one.

    Requires the *current* key to authenticate — this covers voluntary rotation, not
    a lost-key recovery flow (that needs email verification, out of scope for MVP;
    see CLAUDE.md TODOs). Losing the one-time key today still means re-signing up.
    """
    new_key = generate_api_key()
    user.api_key_hash = hash_api_key(new_key)
    db.add(user)
    await db.commit()
    return RotateKeyResponse(api_key=new_key)
