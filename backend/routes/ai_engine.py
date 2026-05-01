# =============================================================
#  MANDIR MATRIMONY — Unified AI Engine
#  backend/routes/ai_engine.py
#  Single endpoint for all 9 AI features
# =============================================================

from __future__ import annotations
import os
import json
from typing import Optional, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import httpx

from .auth import get_current_profile_id

router = APIRouter(prefix="/api/ai", tags=["ai"])

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1500

# =============================================================
# SYSTEM PROMPT — Jyotish Expert Context
# =============================================================

JYOTISH_SYSTEM = """You are Pandit Ji, the AI Jyotish advisor for Mandir Matrimony — 
North America's premier Hindu matrimony platform. You are deeply knowledgeable in:
- Vedic astrology (Jyotish) using Lahiri ayanamsa
- Ashtakoota matching system (all 8 Koots)
- Mangal, Nadi, Bhakoot and Gana Doshas
- Vimshottari Dasha system
- Hindu wedding traditions across all communities
- The specific challenges and joys of the Indian diaspora in Canada and USA

Your tone is warm, wise, culturally sensitive, and encouraging. You write in clear English 
with occasional Sanskrit terms (always explained). You never make definitive predictions — 
you offer guidance and insight. You respect all Hindu communities equally.

Always be concise, meaningful, and personal. Use the actual names and data provided."""


# =============================================================
# FEATURE PROMPTS
# =============================================================

def build_prompt(feature: str, data: dict) -> str:

    if feature == "compatibility_report":
        return f"""Generate a personalized Vedic compatibility report for this couple.

PROFILE A: {data.get('name_a')} — Rashi: {data.get('rashi_a')}, Nakshatra: {data.get('nakshatra_a')}, 
Gana: {data.get('gana_a')}, Nadi: {data.get('nadi_a')}, Mahadasha: {data.get('mahadasha_a')}
Community: {data.get('caste_a')}, Gotra: {data.get('gotra_a')}

PROFILE B: {data.get('name_b')} — Rashi: {data.get('rashi_b')}, Nakshatra: {data.get('nakshatra_b')},
Gana: {data.get('gana_b')}, Nadi: {data.get('nadi_b')}, Mahadasha: {data.get('mahadasha_b')}
Community: {data.get('caste_b')}, Gotra: {data.get('gotra_b')}

ASHTAKOOTA SCORES:
- Total: {data.get('total_score')}/36 ({data.get('compatibility_level')})
- Varna: {data.get('varna_score')}/1, Vashya: {data.get('vashya_score')}/2
- Tara: {data.get('tara_score')}/3, Yoni: {data.get('yoni_score')}/4
- Graha Maitri: {data.get('graha_maitri_score')}/5, Gana: {data.get('gana_score')}/6
- Bhakoot: {data.get('bhakoot_score')}/7, Nadi: {data.get('nadi_score')}/8

DOSHAS: Nadi Dosha: {data.get('nadi_dosha')}, Bhakoot Dosha: {data.get('bhakoot_dosha')}, 
Gana Dosha: {data.get('gana_dosha')}, Mangal compatible: {data.get('mangal_match')}
Same Gotra: {data.get('same_gotra')}

Write a warm, insightful 4-paragraph compatibility reading covering:
1. Overall compatibility energy and what their combined Nakshatra energies mean
2. Strengths of this match (highlight high-scoring Koots)
3. Areas to be mindful of (address any Doshas honestly but gently, with remedies if relevant)
4. A forward-looking blessing for their journey

Use their actual names. Be personal, not generic."""

    elif feature == "bio_writer":
        return f"""Write a warm, authentic matrimony profile bio for {data.get('name')}.

Their answers:
- About themselves: {data.get('about_self')}
- Their family: {data.get('about_family')}
- Their interests: {data.get('interests')}
- What they're looking for: {data.get('looking_for')}
- Their location: {data.get('city')}, {data.get('country')}
- Community: {data.get('community')}
- Profession: {data.get('occupation')}

Write a 3-paragraph bio (150-200 words) that feels genuine, warm and personal.
First paragraph: who they are. Second: their life and values. Third: what they're looking for.
Do NOT start with their name. Do NOT use clichés like "fun-loving" or "family-oriented"."""

    elif feature == "match_explanation":
        return f"""Explain in plain, warm English why {data.get('name_a')} and {data.get('name_b')} 
are a {data.get('compatibility_level')} match ({data.get('total_score')}/36 Gunas).

Their key compatibility points:
- Nakshatra combination: {data.get('nakshatra_a')} + {data.get('nakshatra_b')}
- Strongest Koots: {data.get('strong_koots')}
- Weakest Koots: {data.get('weak_koots')}
- Dosha situation: {data.get('dosha_summary')}

Write 2 paragraphs maximum. First paragraph explains what makes them compatible.
Second paragraph (if any doshas) addresses concerns gently with context.
Use simple language — imagine explaining to someone who knows nothing about Jyotish."""

    elif feature == "conversation_starter":
        return f"""Suggest 3 conversation starters for {data.get('name_a')} to send to {data.get('name_b')} 
on a Hindu matrimony platform. They just matched.

{data.get('name_a')}'s profile: {data.get('occupation_a')} from {data.get('city_a')}, 
interests: {data.get('interests_a')}, community: {data.get('community_a')}

{data.get('name_b')}'s profile: {data.get('occupation_b')} from {data.get('city_b')},
interests: {data.get('interests_b')}, community: {data.get('community_b')}

Generate exactly 3 message options:
1. A light, curious opener about something specific from their profile
2. A shared experience or diaspora connection angle
3. A slightly more personal question about values or family

Format as JSON array: [{{"label": "Curious opener", "message": "..."}}, ...]
Keep each under 40 words. Warm, not cheesy. Culturally appropriate."""

    elif feature == "astrologer_chat":
        return f"""The user is asking our Jyotish advisor a question about their compatibility or Kundali.

User's context: Rashi {data.get('user_rashi')}, Nakshatra {data.get('user_nakshatra')},
Current Mahadasha: {data.get('user_mahadasha')}
{f"Partner context: Rashi {data.get('partner_rashi')}, Nakshatra {data.get('partner_nakshatra')}" if data.get('partner_rashi') else ""}

Their question: {data.get('question')}

Answer as Pandit Ji — warm, knowledgeable, 2-3 paragraphs. If the question needs 
personal birth chart analysis you don't have, say so honestly and suggest what 
additional information would help. Never make absolute predictions."""

    elif feature == "parent_biodata":
        return f"""Generate a formal Indian matrimony biodata document for {data.get('name')}'s parents to share.

Profile details:
- Full name: {data.get('full_name')}
- Date of birth: {data.get('dob')}
- Community/Caste: {data.get('community')}
- Gotra: {data.get('gotra')}
- Rashi/Nakshatra: {data.get('rashi')} / {data.get('nakshatra')}
- Mangal Dosha: {data.get('mangal_dosha')}
- Education: {data.get('education')}
- Occupation: {data.get('occupation')}
- Location: {data.get('city')}, {data.get('country')}
- Immigration status: {data.get('immigration_status')}
- Father's occupation: {data.get('father_occupation')}
- Mother's occupation: {data.get('mother_occupation')}
- Family type: {data.get('family_type')}
- About family: {data.get('about_family')}

Generate a formal, respectful biodata in the traditional Indian format.
Include all standard sections: Personal Details, Astrological Details, 
Education & Career, Family Details, Expected Partner.
Use respectful formal language appropriate for parents to share."""

    elif feature == "auspicious_dates":
        return f"""Recommend 3 auspicious time windows for {data.get('name_a')} and {data.get('name_b')} 
to have their first meeting, based on Vedic astrology.

{data.get('name_a')}: Current Mahadasha {data.get('mahadasha_a')}, Antardasha {data.get('antardasha_a')},
Rashi {data.get('rashi_a')}, Nakshatra {data.get('nakshatra_a')}

{data.get('name_b')}: Current Mahadasha {data.get('mahadasha_b')}, Antardasha {data.get('antardasha_b')},
Rashi {data.get('rashi_b')}, Nakshatra {data.get('nakshatra_b')}

Current date context: {data.get('current_date')}

Recommend 3 time windows in the next 3 months. For each provide:
- The time window (e.g. "March 15-22, 2026")
- Why it's auspicious based on their Dasha periods
- Best day of the week and time of day
- Any tithi or nakshatra considerations

Be specific but acknowledge this is guidance, not absolute prescription.
Format as JSON: [{{"window": "...", "reason": "...", "best_day": "...", "note": "..."}}]"""

    elif feature == "conversation_coach":
        return f"""Privately coach {data.get('user_name')} on improving their conversation with {data.get('match_name')}.

Conversation summary (last 10 messages):
{data.get('conversation_summary')}

{data.get('user_name')}'s message pattern: {data.get('pattern_analysis')}
Days since last message: {data.get('days_silent')}

Give 2-3 specific, actionable suggestions. Be warm and encouraging, not critical.
Focus on what they could say or do next. Reference specific things from the conversation.
Keep it under 100 words. Private coaching tone — like a wise friend advising them."""

    elif feature == "silence_breaker":
        return f"""The conversation between {data.get('name_a')} and {data.get('name_b')} 
has been silent for {data.get('days_silent')} days.

Last message was from: {data.get('last_sender')}
Last message content: "{data.get('last_message')}"

{data.get('name_a')}'s interests: {data.get('interests_a')}
{data.get('name_b')}'s interests: {data.get('interests_b')}
Something they have in common: {data.get('common_ground')}

Suggest ONE perfect re-engagement message for {data.get('name_a')} to send.
It should feel natural, not desperate. Reference something real from their profiles 
or a timely cultural moment (festival, season). Under 30 words.
Return just the message text, nothing else."""

    else:
        raise ValueError(f"Unknown feature: {feature}")


# =============================================================
# REQUEST / RESPONSE MODELS
# =============================================================

class AIRequest(BaseModel):
    feature: str
    data: dict[str, Any]
    stream: bool = False


class AIResponse(BaseModel):
    feature: str
    result: Any          # str for most, list/dict for JSON features
    tokens_used: int
    cost_usd: float


# =============================================================
# COST CALCULATOR
# =============================================================

def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    # Claude Sonnet 4: $3/M input, $15/M output
    return round((input_tokens * 3 + output_tokens * 15) / 1_000_000, 6)


# =============================================================
# JSON FEATURES (return structured data)
# =============================================================

JSON_FEATURES = {"conversation_starter", "auspicious_dates"}


# =============================================================
# MAIN AI ENDPOINT
# =============================================================

@router.post("/generate", response_model=AIResponse)
async def generate_ai_content(
    body: AIRequest,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id),
):
    """
    Unified AI endpoint for all 9 Mandir Matrimony AI features.
    
    Features:
    - compatibility_report: Full Jyotish compatibility narrative
    - bio_writer: Profile bio from user answers
    - match_explanation: Plain-English match explanation
    - conversation_starter: 3 culturally-appropriate openers
    - astrologer_chat: Jyotish Q&A with Pandit Ji
    - parent_biodata: Formal biodata document
    - auspicious_dates: Best meeting windows from Dasha
    - conversation_coach: Private conversation improvement tips
    - silence_breaker: Single re-engagement message
    """

    valid_features = {
        "compatibility_report", "bio_writer", "match_explanation",
        "conversation_starter", "astrologer_chat", "parent_biodata",
        "auspicious_dates", "conversation_coach", "silence_breaker"
    }

    if body.feature not in valid_features:
        raise HTTPException(400, f"Invalid feature. Must be one of: {', '.join(valid_features)}")

    try:
        prompt = build_prompt(body.feature, body.data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Call Claude API
    headers = {
        "Content-Type": "application/json",
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": JYOTISH_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)

    if resp.status_code != 200:
        raise HTTPException(502, f"AI service error: {resp.text}")

    data = resp.json()
    raw_text = data["content"][0]["text"]
    input_tokens = data["usage"]["input_tokens"]
    output_tokens = data["usage"]["output_tokens"]
    cost = calculate_cost(input_tokens, output_tokens)

    # Parse JSON for structured features
    if body.feature in JSON_FEATURES:
        try:
            # Extract JSON from response
            import re
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            result = json.loads(json_match.group()) if json_match else raw_text
        except Exception:
            result = raw_text
    else:
        result = raw_text

    # Log usage for billing (in production: save to DB)
    print(f"AI usage — feature: {body.feature}, tokens: {input_tokens}+{output_tokens}, cost: ${cost}")

    return AIResponse(
        feature=body.feature,
        result=result,
        tokens_used=input_tokens + output_tokens,
        cost_usd=cost,
    )


# =============================================================
# CONVENIENCE ENDPOINTS (for frontend simplicity)
# =============================================================

@router.post("/compatibility/{target_profile_id}")
async def get_compatibility_report(
    target_profile_id: UUID,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id),
):
    """Generate AI compatibility report for two matched profiles."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        # Fetch both profiles and their Kundali
        rows = await conn.fetch("""
            SELECT p.id, p.full_name, p.caste, p.gotra,
                   k.rashi, k.nakshatra, k.gana, k.nadi,
                   k.mangal_dosha, k.current_mahadasha, k.current_antardasha
            FROM profiles p
            LEFT JOIN kundali k ON k.profile_id = p.id
            WHERE p.id = ANY($1)
        """, [str(profile_id), str(target_profile_id)])

        if len(rows) < 2:
            raise HTTPException(404, "One or both profiles not found or missing Kundali")

        profiles = {str(r["id"]): dict(r) for r in rows}
        pa = profiles[str(profile_id)]
        pb = profiles[str(target_profile_id)]

        # Fetch Ashtakoota scores
        score = await conn.fetchrow("""
            SELECT * FROM ashtakoota_scores
            WHERE profile_id_a = $1 AND profile_id_b = $2
        """,
            min(str(profile_id), str(target_profile_id)),
            max(str(profile_id), str(target_profile_id))
        )

    if not score:
        raise HTTPException(404, "Compatibility score not yet computed. Please try again shortly.")

    ai_data = {
        "name_a": pa["full_name"], "name_b": pb["full_name"],
        "rashi_a": pa["rashi"], "rashi_b": pb["rashi"],
        "nakshatra_a": pa["nakshatra"], "nakshatra_b": pb["nakshatra"],
        "gana_a": pa["gana"], "gana_b": pb["gana"],
        "nadi_a": pa["nadi"], "nadi_b": pb["nadi"],
        "mahadasha_a": pa["current_mahadasha"], "mahadasha_b": pb["current_mahadasha"],
        "caste_a": pa["caste"], "caste_b": pb["caste"],
        "gotra_a": pa["gotra"], "gotra_b": pb["gotra"],
        "total_score": score["total_score"],
        "compatibility_level": score["compatibility_level"],
        "varna_score": score["varna_score"], "vashya_score": score["vashya_score"],
        "tara_score": score["tara_score"], "yoni_score": score["yoni_score"],
        "graha_maitri_score": score["graha_maitri_score"],
        "gana_score": score["gana_score"], "bhakoot_score": score["bhakoot_score"],
        "nadi_score": score["nadi_score"],
        "nadi_dosha": score["nadi_dosha_present"],
        "bhakoot_dosha": score["bhakoot_dosha_present"],
        "gana_dosha": score["gana_dosha_present"],
        "mangal_match": score["mangal_dosha_match"],
        "same_gotra": score["same_gotra"],
    }

    return await generate_ai_content(
        AIRequest(feature="compatibility_report", data=ai_data),
        request, profile_id
    )


@router.post("/biodata")
async def get_parent_biodata(
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id),
):
    """Generate formal parent biodata for the current user's profile."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT p.*, cd.city, cd.immigration_status, cd.province,
                   pd.education_level, pd.occupation,
                   fd.father_occupation, fd.mother_occupation, fd.family_type, fd.about_family,
                   k.rashi, k.nakshatra, k.mangal_dosha
            FROM profiles p
            LEFT JOIN canada_details cd ON cd.profile_id = p.id
            LEFT JOIN professional_details pd ON pd.profile_id = p.id
            LEFT JOIN family_details fd ON fd.profile_id = p.id
            LEFT JOIN kundali k ON k.profile_id = p.id
            WHERE p.id = $1
        """, str(profile_id))

    if not row:
        raise HTTPException(404, "Profile not found")

    r = dict(row)
    ai_data = {
        "name": r.get("full_name","").split()[0],
        "full_name": r.get("full_name"),
        "dob": str(r.get("date_of_birth","")),
        "community": r.get("caste"), "gotra": r.get("gotra"),
        "rashi": r.get("rashi"), "nakshatra": r.get("nakshatra"),
        "mangal_dosha": "Yes" if r.get("mangal_dosha") else "No",
        "education": r.get("education_level"), "occupation": r.get("occupation"),
        "city": r.get("city"), "country": "Canada",
        "immigration_status": r.get("immigration_status"),
        "father_occupation": r.get("father_occupation"),
        "mother_occupation": r.get("mother_occupation"),
        "family_type": r.get("family_type"),
        "about_family": r.get("about_family"),
    }

    return await generate_ai_content(
        AIRequest(feature="parent_biodata", data=ai_data),
        request, profile_id
    )
