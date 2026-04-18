from fastapi import APIRouter, Depends, Request
from uuid import UUID
from typing import Optional
from .auth import get_current_profile_id

router = APIRouter(prefix="/api/matches", tags=["matches"])

@router.get("/feed")
async def get_match_feed(page: int=1, page_size: int=20, request: Request=None, profile_id: UUID=Depends(get_current_profile_id)):
    return {"profiles": [], "page": page, "total": 0}

@router.get("/compatibility/{target_id}")
async def get_compatibility(target_id: UUID, request: Request=None, profile_id: UUID=Depends(get_current_profile_id)):
    return {"is_computed": False}

@router.post("/interests/{target_id}", status_code=201)
async def send_interest(target_id: UUID, request: Request=None, profile_id: UUID=Depends(get_current_profile_id)):
    return {"status": "interest_sent"}

@router.put("/interests/{interest_id}/accept")
async def accept_interest(interest_id: UUID, request: Request=None, profile_id: UUID=Depends(get_current_profile_id)):
    return {"status": "accepted"}