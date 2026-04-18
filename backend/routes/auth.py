from fastapi import APIRouter, Header, Request
from uuid import UUID
import uuid

router = APIRouter(prefix="/api/auth", tags=["auth"])

async def get_current_user(authorization: str = Header(default="Bearer demo")):
    return {"user_id": "demo-user", "email": "demo@mandirmatrimony.ca"}

async def get_current_profile_id(authorization: str = Header(default="Bearer demo"), request: Request = None):
    return uuid.UUID("00000000-0000-0000-0000-000000000001")

@router.post("/webhook/clerk")
async def clerk_webhook(request: Request):
    return {"ok": True}