from fastapi import APIRouter, Depends, Request
from uuid import UUID
from typing import Optional
from pydantic import BaseModel
from .auth import get_current_user, get_current_profile_id

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

class CreateProfile(BaseModel):
    full_name: str
    gender: str
    date_of_birth: str
    display_name: Optional[str]=None
    height_cm: Optional[int]=None
    marital_status: str="never_married"
    caste: Optional[str]=None
    gotra: Optional[str]=None
    mother_tongue: Optional[str]=None
    dietary_preference: Optional[str]=None
    about_me: Optional[str]=None

class CanadaDetails(BaseModel):
    immigration_status: str
    province: Optional[str]=None
    city: Optional[str]=None
    willing_to_relocate: bool=True

class PartnerPrefs(BaseModel):
    age_min: Optional[int]=None
    age_max: Optional[int]=None
    min_guna_score: int=18
    mangal_dosha_pref: str="any"

@router.post("/", status_code=201)
async def create_profile(body: CreateProfile, request: Request, current_user: dict=Depends(get_current_user)):
    return {"profile_id": "demo"}

@router.put("/canada")
async def upsert_canada(body: CanadaDetails, request: Request, profile_id: UUID=Depends(get_current_profile_id)):
    return {"ok": True}

@router.put("/preferences")
async def upsert_prefs(body: PartnerPrefs, request: Request, profile_id: UUID=Depends(get_current_profile_id)):
    return {"ok": True}

@router.get("/{target_id}")
async def get_profile(target_id: UUID, request: Request, profile_id: UUID=Depends(get_current_profile_id)):
    return {"id": str(target_id)}