from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import CreditRequest, User
from app.schemas import CreditRequestItem

router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger(__name__)

# MVP-simple billing, on purpose: this app never touches card data or runs payment
# webhooks. A user asks for credits, pays through an external link the operator sets
# up (Stripe Payment Link, PayPal.me, invoice — whatever), and a human grants the
# credits by hand once they've actually confirmed the payment. No automated charging
# means no PCI/webhook surface and no payment-policy pages to have ready for an MVP.


class CreditsResponse(BaseModel):
    credits: int


class CreditRequestResponse(BaseModel):
    message: str
    payment_link: str | None = None
    support_contact: str | None = None


@router.get("/credits", response_model=CreditsResponse)
async def get_credits(user: User = Depends(get_current_user)):
    return CreditsResponse(credits=user.credits)


@router.post("/request-credits", response_model=CreditRequestResponse)
async def request_credits(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Logs the request for the operator to see and act on — no automated charge happens
    here. Pair with `payment_link` (if configured) and grant credits afterwards via
    POST /billing/admin/grant-credits once payment is confirmed by a human. Persisted as
    a CreditRequest row (not just a log line) so GET /billing/requests can show the user
    their own pending/granted history instead of a one-shot toast they might miss."""
    logger.info("Credit request from user_id=%s email=%s", user.id, user.email)
    db.add(CreditRequest(user_id=user.id, status="pending"))
    await db.commit()

    if settings.payment_link_url:
        message = (
            "Pay via the link below, then we'll credit your account once payment is confirmed."
        )
    else:
        message = (
            "Credit top-ups aren't self-serve yet — reply to your signup email to arrange one."
        )
    return CreditRequestResponse(
        message=message,
        payment_link=settings.payment_link_url or None,
        support_contact=settings.support_contact or None,
    )


@router.get("/requests", response_model=list[CreditRequestItem])
async def list_credit_requests(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The caller's own credit-request history — lets the UI show a pending request
    instead of just a toast that's easy to miss and forget about."""
    result = await db.execute(
        select(CreditRequest)
        .where(CreditRequest.user_id == user.id)
        .order_by(CreditRequest.created_at.desc())
        .limit(20)
    )
    return result.scalars().all()


class GrantCreditsRequest(BaseModel):
    email: str
    credits: int


class GrantCreditsResponse(BaseModel):
    email: str
    credits: int


@router.post("/admin/grant-credits", response_model=GrantCreditsResponse)
async def admin_grant_credits(
    body: GrantCreditsRequest,
    db: AsyncSession = Depends(get_db),
    x_admin_key: str | None = Header(default=None),
):
    """Human-in-the-loop credit grant. Protected by a shared operator secret
    (ADMIN_API_KEY), not a per-user API key — call this yourself after verifying a
    payment came in, don't wire it up to anything automated."""
    if not settings.admin_api_key:
        raise HTTPException(status_code=501, detail="ADMIN_API_KEY is not configured")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="No user with that email")

    user.credits += body.credits
    db.add(user)
    # Resolve any open requests so the user's history (and UI) stops showing "pending" —
    # this grant is presumably what those requests were for.
    await db.execute(
        update(CreditRequest)
        .where(CreditRequest.user_id == user.id, CreditRequest.status == "pending")
        .values(status="granted", resolved_at=datetime.now(timezone.utc))
    )
    await db.commit()
    logger.info(
        "Admin granted %d credits to %s (new total: %d)", body.credits, body.email, user.credits
    )
    return GrantCreditsResponse(email=user.email, credits=user.credits)
