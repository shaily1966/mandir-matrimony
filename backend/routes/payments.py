# =============================================================
#  MANDIR MATRIMONY — Payments + AI Report Fulfillment
#  backend/routes/payments.py
#
#  Flow:
#  1. User clicks "Get Full Report ($4.99)"
#  2. POST /api/payments/report/intent  → Stripe PaymentIntent
#  3. Frontend shows Stripe payment sheet
#  4. User pays → Stripe fires webhook
#  5. POST /api/payments/webhook/stripe → fulfills report
#  6. AI engine generates compatibility report + parent biodata + auspicious dates
#  7. Report saved to premium_reports table
#  8. User can fetch report via GET /api/payments/report/{target_id}
# =============================================================

from __future__ import annotations
import os
import json
import httpx
from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from .auth import get_current_profile_id

try:
    import stripe
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
except ImportError:
    stripe = None

router = APIRouter(prefix="/api/payments", tags=["payments"])

REPORT_PRICE_CENTS = int(os.environ.get("REPORT_PRICE_CENTS", "499"))   # $4.99 CAD
ANTHROPIC_API_URL  = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL       = "claude-sonnet-4-20250514"


# =============================================================
# MODELS
# =============================================================

class ReportIntent(BaseModel):
    target_profile_id: UUID
    report_type: str = "full_compatibility"


class ReportResponse(BaseModel):
    is_purchased: bool
    report: dict | None = None


# =============================================================
# STEP 1 — Create Stripe PaymentIntent
# =============================================================

@router.post("/report/intent")
async def create_report_intent(
    body: ReportIntent,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id),
):
    """
    Creates a Stripe PaymentIntent for a $4.99 full compatibility report.
    Returns client_secret for frontend Stripe.js to complete payment.
    """
    if not stripe:
        raise HTTPException(500, "Stripe not configured")

    # Check if already purchased
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("""
            SELECT id FROM premium_reports
            WHERE purchaser_profile_id = $1
              AND subject_profile_id_b = $2
              AND paid_at IS NOT NULL
        """, str(profile_id), str(body.target_profile_id))

        if existing:
            raise HTTPException(409, "Report already purchased. Use GET /api/payments/report/{target_id} to retrieve it.")

    intent = stripe.PaymentIntent.create(
        amount=REPORT_PRICE_CENTS,
        currency="cad",
        metadata={
            "profile_id_a":    str(profile_id),
            "profile_id_b":    str(body.target_profile_id),
            "report_type":     body.report_type,
            "product":         "mandir_matrimony_report",
        },
        description=f"Mandir Matrimony Full Report — {body.report_type}",
    )

    return {
        "client_secret": intent["client_secret"],
        "amount_cents":  REPORT_PRICE_CENTS,
        "currency":      "CAD",
    }


# =============================================================
# STEP 2 — Stripe Webhook → Fulfill Report
# =============================================================

@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe fires this after successful payment.
    We generate the AI report and save it.
    """
    payload = await request.body()
    sig     = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        )
    except Exception as e:
        raise HTTPException(400, f"Invalid Stripe signature: {e}")

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]
        meta   = intent.get("metadata", {})

        if meta.get("product") != "mandir_matrimony_report":
            return {"ok": True}   # not our product

        await _fulfill_report(
            pool           = request.app.state.pool,
            profile_id_a   = meta["profile_id_a"],
            profile_id_b   = meta["profile_id_b"],
            report_type    = meta.get("report_type", "full_compatibility"),
            stripe_intent  = intent["id"],
            amount_cents   = intent["amount"],
        )

    return {"ok": True}


# =============================================================
# STEP 3 — AI Report Fulfillment (called after payment)
# =============================================================

async def _fulfill_report(
    pool, profile_id_a: str, profile_id_b: str,
    report_type: str, stripe_intent: str, amount_cents: int
):
    """
    Fetches both profiles + Ashtakoota scores,
    calls Claude for all AI report sections,
    saves to premium_reports table.
    """
    async with pool.acquire() as conn:

        # ── 1. Check not already fulfilled ───────────────────
        exists = await conn.fetchval(
            "SELECT 1 FROM premium_reports WHERE stripe_payment_intent_id = $1",
            stripe_intent
        )
        if exists:
            return

        # ── 2. Fetch both profiles ────────────────────────────
        rows = await conn.fetch("""
            SELECT p.id, p.full_name, p.caste, p.gotra,
                   p.date_of_birth, p.mother_tongue,
                   cd.city, cd.immigration_status,
                   pd.education_level, pd.occupation,
                   fd.father_occupation, fd.mother_occupation,
                   fd.family_type, fd.about_family,
                   k.rashi, k.nakshatra, k.gana, k.nadi,
                   k.mangal_dosha, k.current_mahadasha, k.current_antardasha
            FROM profiles p
            LEFT JOIN canada_details cd      ON cd.profile_id = p.id
            LEFT JOIN professional_details pd ON pd.profile_id = p.id
            LEFT JOIN family_details fd       ON fd.profile_id = p.id
            LEFT JOIN kundali k               ON k.profile_id = p.id
            WHERE p.id = ANY($1)
        """, [profile_id_a, profile_id_b])

        if len(rows) < 2:
            print(f"Report fulfillment failed: missing profiles for {profile_id_a}, {profile_id_b}")
            return

        profiles = {str(r["id"]): dict(r) for r in rows}
        pa = profiles[profile_id_a]
        pb = profiles[profile_id_b]

        # ── 3. Fetch Ashtakoota scores ────────────────────────
        score = await conn.fetchrow("""
            SELECT * FROM ashtakoota_scores
            WHERE profile_id_a = $1 AND profile_id_b = $2
        """,
            min(profile_id_a, profile_id_b),
            max(profile_id_a, profile_id_b)
        )

        # ── 4. Generate all AI sections ───────────────────────
        report_data = {}

        # Section A: Compatibility narrative
        report_data["compatibility_narrative"] = await _call_claude(
            _prompt_compatibility(pa, pb, score)
        )

        # Section B: Match explanation (plain English)
        report_data["match_explanation"] = await _call_claude(
            _prompt_match_explanation(pa, pb, score)
        )

        # Section C: Parent biodata for profile A
        report_data["parent_biodata"] = await _call_claude(
            _prompt_parent_biodata(pa)
        )

        # Section D: Auspicious dates
        report_data["auspicious_dates"] = await _call_claude(
            _prompt_auspicious_dates(pa, pb),
            expect_json=True
        )

        # Section E: Conversation starters
        report_data["conversation_starters"] = await _call_claude(
            _prompt_conversation_starters(pa, pb),
            expect_json=True
        )

        # ── 5. Save report to DB ──────────────────────────────
        await conn.execute("""
            INSERT INTO premium_reports (
                purchaser_profile_id, subject_profile_id_a, subject_profile_id_b,
                report_type, report_data, stripe_payment_intent_id,
                amount_cad_cents, currency, paid_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'CAD', NOW())
            ON CONFLICT (stripe_payment_intent_id) DO NOTHING
        """,
            profile_id_a, profile_id_a, profile_id_b,
            report_type, json.dumps(report_data),
            stripe_intent, amount_cents
        )

        print(f"Report fulfilled for {pa['full_name']} x {pb['full_name']}")


# =============================================================
# STEP 4 — Fetch Purchased Report
# =============================================================

@router.get("/report/{target_profile_id}", response_model=ReportResponse)
async def get_report(
    target_profile_id: UUID,
    request: Request,
    profile_id: UUID = Depends(get_current_profile_id),
):
    """
    Returns the purchased AI report for two profiles.
    Returns is_purchased=False if not yet paid.
    """
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT report_data, paid_at FROM premium_reports
            WHERE purchaser_profile_id = $1
              AND subject_profile_id_b = $2
              AND paid_at IS NOT NULL
            ORDER BY paid_at DESC
            LIMIT 1
        """, str(profile_id), str(target_profile_id))

    if not row:
        return ReportResponse(is_purchased=False)

    return ReportResponse(
        is_purchased=True,
        report=json.loads(row["report_data"]) if isinstance(row["report_data"], str) else row["report_data"]
    )


# =============================================================
# CLAUDE API HELPER
# =============================================================

JYOTISH_SYSTEM = """You are Pandit Ji, the AI Jyotish advisor for Mandir Matrimony —
North America's premier Hindu matrimony platform. You are deeply knowledgeable in Vedic 
astrology, Ashtakoota matching, and the Indian diaspora experience in Canada and USA.
Your tone is warm, wise, culturally sensitive, and encouraging. Write in clear English 
with occasional Sanskrit terms (always explained). Use actual names from the data provided."""


async def _call_claude(prompt: str, expect_json: bool = False) -> str | list | dict:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1200,
        "system": JYOTISH_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)

    if resp.status_code != 200:
        print(f"Claude API error: {resp.text}")
        return "Report section temporarily unavailable."

    text = resp.json()["content"][0]["text"]

    if expect_json:
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return text


# =============================================================
# PROMPT BUILDERS
# =============================================================

def _prompt_compatibility(pa: dict, pb: dict, score) -> str:
    s = dict(score) if score else {}
    return f"""Generate a personalized Vedic compatibility report for this couple.

{pa['full_name']}: Rashi {pa['rashi']}, Nakshatra {pa['nakshatra']}, 
Gana {pa['gana']}, Nadi {pa['nadi']}, Mahadasha {pa['current_mahadasha']},
Community {pa['caste']}, Gotra {pa['gotra']}

{pb['full_name']}: Rashi {pb['rashi']}, Nakshatra {pb['nakshatra']},
Gana {pb['gana']}, Nadi {pb['nadi']}, Mahadasha {pb['current_mahadasha']},
Community {pb['caste']}, Gotra {pb['gotra']}

Ashtakoota: {s.get('total_score','?')}/36 ({s.get('compatibility_level','?')})
Varna {s.get('varna_score','?')}/1 · Vashya {s.get('vashya_score','?')}/2 · Tara {s.get('tara_score','?')}/3
Yoni {s.get('yoni_score','?')}/4 · Graha Maitri {s.get('graha_maitri_score','?')}/5
Gana {s.get('gana_score','?')}/6 · Bhakoot {s.get('bhakoot_score','?')}/7 · Nadi {s.get('nadi_score','?')}/8
Nadi Dosha: {s.get('nadi_dosha_present','?')} · Bhakoot Dosha: {s.get('bhakoot_dosha_present','?')}
Mangal compatible: {s.get('mangal_dosha_match','?')} · Same Gotra: {s.get('same_gotra','?')}

Write 4 warm paragraphs: (1) overall energy of this union, (2) strengths, 
(3) areas to be mindful of with remedies if needed, (4) a blessing for their journey.
Use their actual names throughout."""


def _prompt_match_explanation(pa: dict, pb: dict, score) -> str:
    s = dict(score) if score else {}
    strong = [k for k,v in {
        'Varna':s.get('varna_score',0),'Vashya':s.get('vashya_score',0),
        'Tara':s.get('tara_score',0),'Yoni':s.get('yoni_score',0),
        'Graha Maitri':s.get('graha_maitri_score',0),'Gana':s.get('gana_score',0),
        'Bhakoot':s.get('bhakoot_score',0),'Nadi':s.get('nadi_score',0)
    }.items() if v and int(float(v)) >= 3]
    return f"""Explain in plain English why {pa['full_name']} and {pb['full_name']} 
scored {s.get('total_score','?')}/36 Gunas ({s.get('compatibility_level','?')} compatibility).
Their strongest koots: {', '.join(strong) if strong else 'balanced across all'}.
Write 2 clear paragraphs a non-astrologer can understand. Use their names."""


def _prompt_parent_biodata(p: dict) -> str:
    return f"""Generate a formal traditional Indian matrimony biodata.

Full name: {p['full_name']} | DOB: {p['date_of_birth']} | Community: {p['caste']} | Gotra: {p['gotra']}
Rashi: {p['rashi']} | Nakshatra: {p['nakshatra']} | Mangal Dosha: {'Yes' if p['mangal_dosha'] else 'No'}
Education: {p['education_level']} | Occupation: {p['occupation']}
Location: {p['city']}, Canada | Status: {p['immigration_status']}
Father: {p['father_occupation']} | Mother: {p['mother_occupation']}
Family type: {p['family_type']} | About family: {p['about_family']}

Format as a traditional Indian biodata with sections:
Personal Details · Astrological Details · Education & Career · Family Details · Contact
Use respectful formal language suitable for parents to share."""


def _prompt_auspicious_dates(pa: dict, pb: dict) -> str:
    return f"""Recommend 3 auspicious time windows for {pa['full_name']} and {pb['full_name']} 
to meet, based on their Dasha periods.

{pa['full_name']}: Mahadasha {pa['current_mahadasha']}, Antardasha {pa['current_antardasha']}, Rashi {pa['rashi']}
{pb['full_name']}: Mahadasha {pb['current_mahadasha']}, Antardasha {pb['current_antardasha']}, Rashi {pb['rashi']}
Today: {date.today().strftime('%B %Y')}

Return JSON array of 3 objects: [{{"window":"...","reason":"...","best_day":"...","note":"..."}}]"""


def _prompt_conversation_starters(pa: dict, pb: dict) -> str:
    return f"""Suggest 3 first messages for {pa['full_name']} to send {pb['full_name']} 
on a Hindu matrimony platform.

{pa['full_name']}: {pa['occupation']} from {pa['city']}, community {pa['caste']}
{pb['full_name']}: {pb['occupation']} from {pb['city']}, community {pb['caste']}

Return JSON: [{{"label":"...","message":"..."}}] — 3 items, each message under 40 words.
Warm, culturally appropriate, not generic."""
