from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import User

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


@router.get("/credits", response_model=CreditsResponse)
async def get_credits(user: User = Depends(get_current_user)):
    return CreditsResponse(credits=user.credits)


@router.post("/request-credits", response_model=CreditRequestResponse)
async def request_credits(user: User = Depends(get_current_user)):
    """Logs the request for the operator to see and act on — no automated charge happens
    here. Pair with `payment_link` (if configured) and grant credits afterwards via
    POST /billing/admin/grant-credits once payment is confirmed by a human."""
    logger.info("Credit request from user_id=%s email=%s", user.id, user.email)
    if settings.payment_link_url:
        message = (
            "Pay via the link below, then we'll credit your account once payment is confirmed."
        )
    else:
        message = (
            "Credit top-ups aren't self-serve yet — reply to your signup email to arrange one."
        )
    return CreditRequestResponse(message=message, payment_link=settings.payment_link_url or None)


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
    await db.commit()
    logger.info(
        "Admin granted %d credits to %s (new total: %d)", body.credits, body.email, user.credits
    )
    return GrantCreditsResponse(email=user.email, credits=user.credits)
