from fastapi import APIRouter, Depends, Request
from uuid import UUID
from typing import Optional
from datetime import date, time as dtime
from pydantic import BaseModel
from .auth import get_current_profile_id

router = APIRouter(prefix="/api/kundali", tags=["kundali"])

class KundaliInput(BaseModel):
    birth_date: str
    birth_time: Optional[str] = None
    birth_place: str
    latitude: float
    longitude: float
    timezone: str = "America/Toronto"

@router.post("/compute")
async def compute_kundali(body: KundaliInput, request: Request, profile_id: UUID=Depends(get_current_profile_id)):
    from jyotish import JyotishEngine
    engine = JyotishEngine()
    bd = date.fromisoformat(body.birth_date)
    bt = dtime.fromisoformat(body.birth_time) if body.birth_time else None
    chart = engine.compute_chart(birth_date=bd, birth_time=bt, birth_place=body.birth_place, latitude=body.latitude, longitude=body.longitude, timezone=body.timezone)
    return {"rashi": chart.rashi, "nakshatra": chart.nakshatra_name, "mangal_dosha": chart.mangal_dosha}

@router.get("/my")
async def get_my_kundali(request: Request, profile_id: UUID=Depends(get_current_profile_id)):
    return {"message": "No kundali yet"}