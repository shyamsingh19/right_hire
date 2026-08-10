from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key, hash_api_key
from app.config import settings
from app.db import get_db
from app.models import Candidate, Evaluation, Job, User
from app.schemas import ApiKeyResetResponse, UserResponse, UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

# Operator-only surface for the `users` table: not exposed under per-user auth since a
# user's own key must never be able to list/edit/delete *other* users. Guarded by the
# same shared ADMIN_API_KEY secret used by POST /billing/admin/grant-credits.


def _require_admin(x_admin_key: str | None) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=501, detail="ADMIN_API_KEY is not configured")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(x_admin_key)
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(x_admin_key)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(x_admin_key)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.email is not None:
        existing = await db.execute(
            select(User).where(User.email == body.email, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already registered")
        user.email = body.email
    if body.credits is not None:
        user.credits = body.credits

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    x_admin_key: str | None = Header(default=None),
):
    """Delete a user and everything scoped under them (jobs, candidates, evaluations) —
    no DB-level cascade exists, so this walks the same order as DELETE /jobs/{id}."""
    _require_admin(x_admin_key)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    job_ids_result = await db.execute(select(Job.id).where(Job.user_id == user_id))
    job_ids = list(job_ids_result.scalars().all())

    if job_ids:
        cand_ids_result = await db.execute(
            select(Candidate.id).where(Candidate.job_id.in_(job_ids))
        )
        cand_ids = list(cand_ids_result.scalars().all())
        if cand_ids:
            await db.execute(sa_delete(Evaluation).where(Evaluation.candidate_id.in_(cand_ids)))
        await db.execute(sa_delete(Candidate).where(Candidate.job_id.in_(job_ids)))
        await db.execute(sa_delete(Job).where(Job.id.in_(job_ids)))

    await db.delete(user)
    await db.commit()


@router.post("/users/{user_id}/reset-api-key", response_model=ApiKeyResetResponse)
async def reset_api_key(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    x_admin_key: str | None = Header(default=None),
):
    """Operator-triggered key reissue — e.g. a user emailed support saying they lost their
    key. Since only the SHA-256 hash is stored (see app/auth.py), the original key can
    never be recovered; this issues a new one and invalidates the old one immediately,
    same mechanics as the self-service POST /auth/rotate-key but callable by an operator
    on the user's behalf. Shown once in the response — store it or lose it again."""
    _require_admin(x_admin_key)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_key = generate_api_key()
    user.api_key_hash = hash_api_key(new_key)
    db.add(user)
    await db.commit()

    logger.info("Admin reset API key for user_id=%s email=%s", user.id, user.email)
    return ApiKeyResetResponse(user_id=user.id, email=user.email, api_key=new_key)
