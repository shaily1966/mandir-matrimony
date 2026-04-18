from __future__ import annotations
import os, logging
from contextlib import asynccontextmanager
import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mandir")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=2, max_size=10)
    logger.info("DB pool ready")
    yield
    await app.state.pool.close()

app = FastAPI(title="Mandir Matrimony API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

from backend.routes.auth import router as auth_router
from backend.routes.profiles import router as profiles_router
from backend.routes.kundali import router as kundali_router
from backend.routes.matches import router as matches_router
from backend.routes.messages import router as messages_router
from backend.routes.payments import router as payments_router

app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(kundali_router)
app.include_router(matches_router)
app.include_router(messages_router)
app.include_router(payments_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "mandirmatrimony.ca"}

@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    logger.error(f"Error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
