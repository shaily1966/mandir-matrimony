# ============================================================
#  MANDIR MATRIMONY — Matches Route (Real DB)
#  backend/routes/matches.py
# ============================================================
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import Optional
from uuid import UUID
from pydantic import BaseModel
import math

from .auth import get_current_profile_id

router = APIRouter(prefix="/api/matches", tags=["matches"])

# ── MODELS ──────────────────────────────────────────────────

class InterestBody(BaseModel):
    message: Optional[str] = None

# ── HELPERS ─────────────────────────────────────────────────

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, '__str__') and type(v).__name__ == 'UUID':
            d[k] = str(v)
    return d

def calculate_age(dob):
    if not dob:
        return None
    from datetime import date
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

def compatibility_level(score):
    if score is None:
        return "unknown"
    if score >= 28:
        return "excellent"
    elif score >= 21:
        return "good"
    elif score >= 18:
        return "average"
    else:
        return "below_average"

# ── MATCH FEED ───────────────────────────────────────────────

@router.get("/feed")
async def get_match_feed(
    page: int = 1,
    page_size: int = 20,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """
    Get paginated match feed sorted by Guna score.
    Filters: opposite gender, respects partner preferences.
    """
    pool = request.app.state.pool
    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        # Get current user's gender and preferences
        me = await conn.fetchrow(
            "SELECT gender FROM profiles WHERE id = $1", profile_id
        )
        if not me:
            raise HTTPException(404, "Profile not found")

        target_gender = "female" if me["gender"] == "male" else "male"

        # Fetch matches: opposite gender, not self, with Guna scores if available
        rows = await conn.fetch("""
            SELECT
                p.id,
                p.full_name,
                p.display_name,
                p.date_of_birth,
                p.height_cm,
                p.caste,
                p.gotra,
                p.mother_tongue,
                p.dietary_preference,
                p.about_me,
                cd.immigration_status,
                cd.province,
                cd.city,
                cd.family_values,
                pd.education_level,
                pd.occupation,
                k.rashi,
                k.nakshatra,
                k.gana,
                k.nadi,
                k.mangal_dosha,
                k.current_mahadasha,
                COALESCE(
                    aks.total_score,
                    0
                ) AS guna_score,
                aks.nadi_dosha_present,
                aks.bhakoot_dosha_present,
                aks.gana_dosha_present,
                aks.mangal_dosha_match,
                aks.varna_score,
                aks.vashya_score,
                aks.tara_score,
                aks.yoni_score,
                aks.graha_maitri_score,
                aks.gana_score AS gana_koot_score,
                aks.bhakoot_score,
                aks.nadi_score,
                (SELECT url FROM photos WHERE profile_id = p.id AND is_primary = TRUE LIMIT 1) AS primary_photo
            FROM profiles p
            LEFT JOIN canada_details cd ON cd.profile_id = p.id
            LEFT JOIN professional_details pd ON pd.profile_id = p.id
            LEFT JOIN kundali k ON k.profile_id = p.id
            LEFT JOIN ashtakoota_scores aks ON (
                (aks.profile_id_a = LEAST($1::uuid, p.id) AND aks.profile_id_b = GREATEST($1::uuid, p.id))
            )
            WHERE p.gender = $2
              AND p.is_active = TRUE
              AND p.id != $1
            ORDER BY guna_score DESC NULLS LAST, p.created_at DESC
            LIMIT $3 OFFSET $4
        """, profile_id, target_gender, page_size, offset)

        total = await conn.fetchval("""
            SELECT COUNT(*) FROM profiles
            WHERE gender = $1 AND is_active = TRUE AND id != $2
        """, target_gender, profile_id)

    profiles = []
    for row in rows:
        d = row_to_dict(row)
        d["age"] = calculate_age(row["date_of_birth"])
        d["guna_score"] = float(d["guna_score"]) if d["guna_score"] else 0
        d["compatibility_level"] = compatibility_level(d["guna_score"])
        profiles.append(d)

    return {
        "profiles": profiles,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0
    }


# ── COMPATIBILITY ────────────────────────────────────────────

@router.get("/compatibility/{target_id}")
async def get_compatibility(
    target_id: UUID,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Get Ashtakoota compatibility score between current user and target."""
    pool = request.app.state.pool
    pid_a = min(str(profile_id), str(target_id))
    pid_b = max(str(profile_id), str(target_id))

    async with pool.acquire() as conn:
        score = await conn.fetchrow("""
            SELECT * FROM ashtakoota_scores
            WHERE profile_id_a = $1 AND profile_id_b = $2
        """, pid_a, pid_b)

    if not score:
        return {"is_computed": False}

    d = row_to_dict(score)
    d["compatibility_level"] = compatibility_level(float(d["total_score"]) if d["total_score"] else 0)
    d["is_computed"] = True
    return d


# ── INTERESTS ────────────────────────────────────────────────

@router.post("/interests/{target_id}", status_code=201)
async def send_interest(
    target_id: UUID,
    body: InterestBody = None,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Send interest to another profile."""
    pool = request.app.state.pool

    if profile_id == target_id:
        raise HTTPException(400, "Cannot send interest to yourself")

    async with pool.acquire() as conn:
        # Check target exists
        target = await conn.fetchrow(
            "SELECT id FROM profiles WHERE id = $1 AND is_active = TRUE", target_id
        )
        if not target:
            raise HTTPException(404, "Profile not found")

        # Check if already sent
        existing = await conn.fetchrow("""
            SELECT id, status FROM interests
            WHERE from_profile_id = $1 AND to_profile_id = $2
        """, profile_id, target_id)

        if existing:
            return {"status": existing["status"], "already_sent": True}

        await conn.execute("""
            INSERT INTO interests (from_profile_id, to_profile_id, message)
            VALUES ($1, $2, $3)
        """, profile_id, target_id, body.message if body else None)

    return {"status": "interest_sent", "already_sent": False}


@router.get("/interests/received")
async def get_received_interests(
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Get interests received by current user."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                i.id AS interest_id,
                i.status,
                i.message,
                i.created_at,
                p.id,
                p.full_name,
                p.display_name,
                p.date_of_birth,
                p.caste,
                cd.city,
                cd.province,
                pd.occupation,
                COALESCE(aks.total_score, 0) AS guna_score,
                (SELECT url FROM photos WHERE profile_id = p.id AND is_primary = TRUE LIMIT 1) AS primary_photo
            FROM interests i
            JOIN profiles p ON p.id = i.from_profile_id
            LEFT JOIN canada_details cd ON cd.profile_id = p.id
            LEFT JOIN professional_details pd ON pd.profile_id = p.id
            LEFT JOIN ashtakoota_scores aks ON (
                aks.profile_id_a = LEAST($1::uuid, p.id)
                AND aks.profile_id_b = GREATEST($1::uuid, p.id)
            )
            WHERE i.to_profile_id = $1
            ORDER BY i.created_at DESC
        """, profile_id)

    result = []
    for row in rows:
        d = row_to_dict(row)
        d["age"] = calculate_age(row["date_of_birth"])
        d["guna_score"] = float(d["guna_score"]) if d["guna_score"] else 0
        result.append(d)

    return {"interests": result, "total": len(result)}


@router.get("/interests/sent")
async def get_sent_interests(
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Get interests sent by current user."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT i.id AS interest_id, i.status, i.created_at,
                   p.id, p.full_name, p.display_name, p.date_of_birth,
                   cd.city, pd.occupation
            FROM interests i
            JOIN profiles p ON p.id = i.to_profile_id
            LEFT JOIN canada_details cd ON cd.profile_id = p.id
            LEFT JOIN professional_details pd ON pd.profile_id = p.id
            WHERE i.from_profile_id = $1
            ORDER BY i.created_at DESC
        """, profile_id)

    return {"interests": [row_to_dict(r) for r in rows]}


@router.put("/interests/{interest_id}/accept")
async def accept_interest(
    interest_id: UUID,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Accept a received interest."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        interest = await conn.fetchrow("""
            SELECT * FROM interests WHERE id = $1 AND to_profile_id = $2
        """, interest_id, profile_id)

        if not interest:
            raise HTTPException(404, "Interest not found")

        await conn.execute("""
            UPDATE interests SET status = 'accepted', updated_at = NOW()
            WHERE id = $1
        """, interest_id)

        # Create conversation if it doesn't exist
        pid_a = min(str(interest["from_profile_id"]), str(profile_id))
        pid_b = max(str(interest["from_profile_id"]), str(profile_id))

        await conn.execute("""
            INSERT INTO conversations (profile_id_a, profile_id_b)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, pid_a, pid_b)

    return {"status": "accepted"}


@router.put("/interests/{interest_id}/decline")
async def decline_interest(
    interest_id: UUID,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Decline a received interest."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE interests SET status = 'declined', updated_at = NOW()
            WHERE id = $1 AND to_profile_id = $2
        """, interest_id, profile_id)
    return {"status": "declined"}


# ── CONVERSATIONS & MESSAGES ─────────────────────────────────

@router.get("/conversations")
async def get_conversations(
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Get all conversations for current user."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                c.id AS conversation_id,
                c.last_message_at,
                p.id AS other_profile_id,
                p.full_name,
                p.display_name,
                (SELECT content FROM messages WHERE conversation_id = c.id ORDER BY created_at DESC LIMIT 1) AS last_message,
                (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id AND sender_id != $1 AND read_at IS NULL) AS unread_count,
                (SELECT url FROM photos WHERE profile_id = p.id AND is_primary = TRUE LIMIT 1) AS primary_photo
            FROM conversations c
            JOIN profiles p ON p.id = CASE
                WHEN c.profile_id_a = $1 THEN c.profile_id_b
                ELSE c.profile_id_a
            END
            WHERE c.profile_id_a = $1 OR c.profile_id_b = $1
            ORDER BY c.last_message_at DESC
        """, profile_id)

    return {"conversations": [row_to_dict(r) for r in rows]}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: UUID,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Get messages in a conversation."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        # Verify user is in conversation
        conv = await conn.fetchrow("""
            SELECT id FROM conversations
            WHERE id = $1 AND (profile_id_a = $2 OR profile_id_b = $2)
        """, conversation_id, profile_id)
        if not conv:
            raise HTTPException(403, "Not a participant in this conversation")

        messages = await conn.fetch("""
            SELECT m.id, m.sender_id, m.content, m.created_at, m.read_at
            FROM messages m
            WHERE m.conversation_id = $1
            ORDER BY m.created_at ASC
            LIMIT 100
        """, conversation_id)

        # Mark messages as read
        await conn.execute("""
            UPDATE messages SET read_at = NOW()
            WHERE conversation_id = $1 AND sender_id != $2 AND read_at IS NULL
        """, conversation_id, profile_id)

    return {"messages": [row_to_dict(m) for m in messages]}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: UUID,
    request: Request = None,
    profile_id: UUID = Depends(get_current_profile_id)
):
    """Send a message in a conversation."""
    pool = request.app.state.pool
    body = await request.json()
    content = body.get("content", "").strip()

    if not content:
        raise HTTPException(400, "Message content cannot be empty")

    async with pool.acquire() as conn:
        # Verify user is in conversation
        conv = await conn.fetchrow("""
            SELECT id FROM conversations
            WHERE id = $1 AND (profile_id_a = $2 OR profile_id_b = $2)
        """, conversation_id, profile_id)
        if not conv:
            raise HTTPException(403, "Not a participant in this conversation")

        msg = await conn.fetchrow("""
            INSERT INTO messages (conversation_id, sender_id, content)
            VALUES ($1, $2, $3)
            RETURNING id, created_at
        """, conversation_id, profile_id, content)

        await conn.execute("""
            UPDATE conversations SET last_message_at = NOW() WHERE id = $1
        """, conversation_id)

    return {"id": str(msg["id"]), "created_at": msg["created_at"].isoformat()}
