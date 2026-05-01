# backend/routes/auth.py
from __future__ import annotations
import os
from uuid import UUID
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

CLERK_PEM_URL = "https://api.clerk.com/v1/jwks"
_jwks_cache: dict = {}


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    async with httpx.AsyncClient() as c:
        r = await c.get(CLERK_PEM_URL, headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}"})
        _jwks_cache = r.json()
    return _jwks_cache


async def get_current_user(authorization: str = Header(...)) -> dict:
    """Dependency: validates Clerk JWT, returns {user_id, email}."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization[7:]
    try:
        jwks = await _get_jwks()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
        if not key:
            raise HTTPException(401, "Unknown signing key")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        payload = jwt.decode(
            token, public_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return {"user_id": payload["sub"], "email": payload.get("email", "")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except Exception:
        raise HTTPException(401, "Invalid token")


async def get_current_profile_id(
    current_user: dict = Depends(get_current_user),
    request: Request = None,
) -> UUID:
    """Dependency: resolves Clerk user_id → internal profile UUID."""
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT p.id FROM profiles p INNER JOIN users u ON u.id = p.user_id WHERE u.auth_provider_id = $1",
            current_user["user_id"]
        )
        if not row:
            raise HTTPException(404, "Profile not found — complete onboarding first")
        return row["id"]


# ── Webhook: sync Clerk user to DB ────────────────────────────
class ClerkWebhookPayload(BaseModel):
    type: str
    data: dict


@router.post("/webhook/clerk")
async def clerk_webhook(payload: ClerkWebhookPayload, request: Request):
    """Clerk webhook — creates user record on signup."""
    if payload.type != "user.created":
        return {"ok": True}

    user_data = payload.data
    pool = request.app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (email, auth_provider, auth_provider_id, is_email_verified)
            VALUES ($1, 'clerk', $2, $3)
            ON CONFLICT (email) DO UPDATE
              SET auth_provider_id = EXCLUDED.auth_provider_id,
                  is_email_verified = EXCLUDED.is_email_verified
        """,
            user_data.get("email_addresses", [{}])[0].get("email_address", ""),
            user_data["id"],
            user_data.get("email_addresses", [{}])[0].get("verification", {}).get("status") == "verified",
        )
    return {"ok": True}
