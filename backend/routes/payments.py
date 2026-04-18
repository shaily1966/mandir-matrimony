from fastapi import APIRouter, Depends, Request
from uuid import UUID
from pydantic import BaseModel
from .auth import get_current_profile_id

router = APIRouter(prefix="/api/payments", tags=["payments"])

class ReportIntent(BaseModel):
    target_profile_id: UUID

@router.post("/report/intent")
async def create_intent(body: ReportIntent, profile_id: UUID=Depends(get_current_profile_id)):
    return {"client_secret": "demo", "amount_cents": 499}

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    return {"ok": True}