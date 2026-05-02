# ============================================================
#  MANDIR MATRIMONY — Profiles Route (Real DB)
#  backend/routes/profiles.py
# ============================================================
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel
from datetime import date
import os, httpx

from .auth import get_current_user, get_current_profile_id

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

# ── MODELS ──────────────────────────────────────────────────

class CreateProfile(BaseModel):
    full_name: str
    gender: str
    date_of_birth: str
    display_name: Optional[str] = None
    height_cm: Optional[int] = None
    marital_status: str = "never_married"
    profile_created_by: str = "self"
    caste: Optional[str] = None
    gotra: Optional[str] = None
    mother_tongue: Optional[str] = None
    dietary_preference: Optional[str] = None
    about_me: Optional[str] = None

class UpdateProfile(BaseModel):
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    height_cm: Optional[int] = None
    marital_status: Optional[str] = None
    caste: Optional[str] = None
    gotra: Optional[str] = None
    mother_tongue: Optional[str] = None
    dietary_preference: Optional[str] = None
    about_me: Optional[str] = None

class CanadaDetails(BaseModel):
    immigration_status: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    years_in_canada: Optional[int] = None
    willing_to_relocate: bool = True
    native_state: Optional[str] = None
    family_type: Optional[str] = None
    family_values: Optional[str] = None
    about_family: Optional[str] = None

class ProfessionalDetails(BaseModel):
    education_level: Optional[str] = None
    field_of_study: Optional[str] = None
    employment_type: Optional[str] = None
    occupation: Optional[str] = None
    employer: Optional[str] = None
    annual_income: Optional[int] = None

class PartnerPrefs(BaseModel):
    pref_age_min: Optional[int] = 18
    pref_age_max: Optional[int] = 45
    pref_immigration: Optional[List[str]] = []
    pref_province: Optional[List[str]] = []
    pref_diet: Optional[List[str]] = []
    pref_min_guna: int = 18
    pref_mangal: str = "any"
    pref_education: str = "any"

class WaitlistEntry(BaseModel):
    name: Optional[str] = None
    email: str
    seeking: Optional[str] = None
    province: Optional[str] = None
    source: str = "landing_waitlist"

# ── HELPERS ─────────────────────────────────────────────────

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)

async def get_profile_by_clerk_id(pool, clerk_user_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM profiles WHERE clerk_user_id = $1 AND is_active = TRUE",
            clerk_user_id
        )
        return row_to_dict(row)

# ── ROUTES ───────────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_profile(
    body: CreateProfile,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Create a new profile. One profile per Clerk user."""
    pool = request.app.state.pool
    clerk_user_id = current_user["sub"]

    async with pool.acquire() as conn:
        # Check if profile already exists
        existing = await conn.fetchrow(
            "SELECT id FROM profiles WHERE clerk_user_id = $1", clerk_user_id
        )
        if existing:
            # Return existing profile id instead of error
            return {"id": str(existing["id"]), "created": False}

        try:
            dob = date.fromisoformat(body.date_of_birth)
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")

        row = await conn.fetchrow("""
            INSERT INTO profiles (
                clerk_user_id, full_name, display_name, gender, date_of_birth,
                height_cm, marital_status, profile_created_by, caste, gotra,
                mother_tongue, dietary_preference, about_me
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            RETURNING id, created_at
        """,
            clerk_user_id, body.full_name, body.display_name, body.gender, dob,
            body.height_cm, body.marital_status, body.profile_created_by,
            body.caste, body.gotra, body.mother_tongue, body.dietary_preference,
            body.about_me
        )
        return {"id": str(row["id"]), "created": True}


@router.get("/me")
async def get_my_profile(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Get the current user's full profile."""
    pool = request.app.state.pool
    clerk_user_id = current_user["sub"]

    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM profiles WHERE clerk_user_id = $1 AND is_active = TRUE",
            clerk_user_id
        )
        if not profile:
            raise HTTPException(404, "Profile not found")

        profile_id = profile["id"]

        canada = await conn.fetchrow(
            "SELECT * FROM canada_details WHERE profile_id = $1", profile_id
        )
        professional = await conn.fetchrow(
            "SELECT * FROM professional_details WHERE profile_id = $1", profile_id
        )
        prefs = await conn.fetchrow(
            "SELECT * FROM partner_preferences WHERE profile_id = $1", profile_id
        )
        kundali = await conn.fetchrow(
            "SELECT * FROM kundali WHERE profile_id = $1", profile_id
        )
        photos = await conn.fetch(
            "SELECT * FROM photos WHERE profile_id = $1 ORDER BY is_primary DESC", profile_id
        )

    result = row_to_dict(profile)
    result["id"] = str(result["id"])
    result["canada"] = row_to_dict(canada)
    result["professional"] = row_to_dict(professional)
    result["preferences"] = row_to_dict(prefs)
    result["kundali"] = row_to_dict(kundali)
    result["photos"] = [row_to_dict(p) for p in photos]
    return result


@router.put("/me")
async def update_my_profile(
    body: UpdateProfile,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Update core profile fields."""
    pool = request.app.state.pool
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return {"ok": True}

    set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
    values = list(updates.values())

    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE profiles SET {set_clauses}, updated_at = NOW() WHERE id = $1",
            profile_id, *values
        )
    return {"ok": True}


@router.put("/canada")
async def upsert_canada(
    body: CanadaDetails,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Create or update Canada/location details."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO canada_details (
                profile_id, immigration_status, province, city, years_in_canada,
                willing_to_relocate, native_state, family_type, family_values, about_family
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (profile_id) DO UPDATE SET
                immigration_status = EXCLUDED.immigration_status,
                province = EXCLUDED.province,
                city = EXCLUDED.city,
                years_in_canada = EXCLUDED.years_in_canada,
                willing_to_relocate = EXCLUDED.willing_to_relocate,
                native_state = EXCLUDED.native_state,
                family_type = EXCLUDED.family_type,
                family_values = EXCLUDED.family_values,
                about_family = EXCLUDED.about_family,
                updated_at = NOW()
        """,
            profile_id, body.immigration_status, body.province, body.city,
            body.years_in_canada, body.willing_to_relocate, body.native_state,
            body.family_type, body.family_values, body.about_family
        )
    return {"ok": True}


@router.put("/professional")
async def upsert_professional(
    body: ProfessionalDetails,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Create or update professional/education details."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO professional_details (
                profile_id, education_level, field_of_study, employment_type,
                occupation, employer, annual_income
            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (profile_id) DO UPDATE SET
                education_level = EXCLUDED.education_level,
                field_of_study = EXCLUDED.field_of_study,
                employment_type = EXCLUDED.employment_type,
                occupation = EXCLUDED.occupation,
                employer = EXCLUDED.employer,
                annual_income = EXCLUDED.annual_income,
                updated_at = NOW()
        """,
            profile_id, body.education_level, body.field_of_study,
            body.employment_type, body.occupation, body.employer, body.annual_income
        )
    return {"ok": True}


@router.put("/preferences")
async def upsert_preferences(
    body: PartnerPrefs,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Create or update partner preferences."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO partner_preferences (
                profile_id, pref_age_min, pref_age_max, pref_immigration,
                pref_province, pref_diet, pref_min_guna, pref_mangal, pref_education
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (profile_id) DO UPDATE SET
                pref_age_min = EXCLUDED.pref_age_min,
                pref_age_max = EXCLUDED.pref_age_max,
                pref_immigration = EXCLUDED.pref_immigration,
                pref_province = EXCLUDED.pref_province,
                pref_diet = EXCLUDED.pref_diet,
                pref_min_guna = EXCLUDED.pref_min_guna,
                pref_mangal = EXCLUDED.pref_mangal,
                pref_education = EXCLUDED.pref_education,
                updated_at = NOW()
        """,
            profile_id, body.pref_age_min, body.pref_age_max,
            body.pref_immigration or [], body.pref_province or [],
            body.pref_diet or [], body.pref_min_guna, body.pref_mangal,
            body.pref_education
        )
    return {"ok": True}


@router.post("/photos")
async def upload_photos(
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Upload profile photos. Stores URLs (extend with S3/Cloudinary as needed)."""
    pool = request.app.state.pool
    form = await request.form()
    visibility = form.get("visibility", "members")
    photos = form.getlist("photos")

    if not photos:
        return {"ok": True, "uploaded": 0}

    # Check existing photo count
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM photos WHERE profile_id = $1", profile_id
        )
        is_first = count == 0

        uploaded = 0
        for i, photo in enumerate(photos[:6]):
            if hasattr(photo, 'filename'):
                # In production: upload to S3/Cloudinary and get URL
                # For now: store a placeholder URL
                url = f"/photos/{profile_id}/{photo.filename}"
                await conn.execute("""
                    INSERT INTO photos (profile_id, url, is_primary, visibility)
                    VALUES ($1, $2, $3, $4)
                """, profile_id, url, (is_first and i == 0), visibility)
                uploaded += 1

        # Mark profile as having photos
        if uploaded > 0:
            await conn.execute(
                "UPDATE profiles SET profile_complete = TRUE, updated_at = NOW() WHERE id = $1",
                profile_id
            )

    return {"ok": True, "uploaded": uploaded}


@router.get("/{target_id}")
async def get_profile(
    target_id: UUID,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Get a specific profile by ID (for viewing matches)."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM profiles WHERE id = $1 AND is_active = TRUE", target_id
        )
        if not profile:
            raise HTTPException(404, "Profile not found")

        canada = await conn.fetchrow(
            "SELECT * FROM canada_details WHERE profile_id = $1", target_id
        )
        professional = await conn.fetchrow(
            "SELECT * FROM professional_details WHERE profile_id = $1", target_id
        )
        kundali = await conn.fetchrow(
            "SELECT rashi, nakshatra, gana, nadi, mangal_dosha, current_mahadasha FROM kundali WHERE profile_id = $1",
            target_id
        )
        photos = await conn.fetch(
            "SELECT url, is_primary FROM photos WHERE profile_id = $1 ORDER BY is_primary DESC LIMIT 3",
            target_id
        )

    result = row_to_dict(profile)
    result["id"] = str(result["id"])
    result["canada"] = row_to_dict(canada)
    result["professional"] = row_to_dict(professional)
    result["kundali"] = row_to_dict(kundali)
    result["photos"] = [row_to_dict(p) for p in photos]
    return result


# ── WAITLIST ─────────────────────────────────────────────────

@router.post("/waitlist", status_code=201, tags=["waitlist"])
async def join_waitlist(body: WaitlistEntry, request: Request):
    """Add email to waitlist."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO waitlist (name, email, seeking, province, source)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (email) DO UPDATE SET
                    name = EXCLUDED.name,
                    seeking = EXCLUDED.seeking,
                    province = EXCLUDED.province,
                    updated_at = NOW()
            """, body.name, body.email, body.seeking, body.province, body.source)
        except Exception as e:
            # Don't fail loudly for duplicate emails
            pass
    return {"ok": True, "message": "Added to waitlist"}
