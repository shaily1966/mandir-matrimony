from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.routes.auth import router as auth_router
from backend.routes.profiles import router as profiles_router
from backend.routes.kundali import router as kundali_router
from backend.routes.matches import router as matches_router
from backend.routes.messages import router as messages_router
from backend.routes.payments import router as payments_router
from backend.routes.ai_engine import router as ai_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mandir")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"],
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    logger.info("DB pool ready")
    yield
    await app.state.pool.close()


app = FastAPI(
    title="Mandir Matrimony API",
    description="Hindu matrimony for the Canadian diaspora — Jyotish-powered",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(kundali_router)
app.include_router(matches_router)
app.include_router(messages_router)
app.include_router(payments_router)
app.include_router(ai_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "mandirmatrimony.ca"}


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
