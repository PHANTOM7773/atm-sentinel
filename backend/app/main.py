from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import APP_NAME, APP_VERSION, CORS_ORIGINS
from .db import init_db
from .routers import cases, cv, cv_enhancement, exports, frames, jobs, system, videos
from .schemas import AlignmentRequest
from .services.security import env_passphrase, session_token

SESSION_COOKIE = "sentinel_session"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {"/api/session", "/api/system/status", "/api/alignment/preview"}


@app.middleware("http")
async def local_session_guard(request: Request, call_next):
    passphrase = env_passphrase()
    path = request.url.path
    if not passphrase or not path.startswith("/api") or path in PUBLIC_PATHS:
        return await call_next(request)
    expected = session_token(passphrase, "atm-sentinel-session")
    provided = request.cookies.get(SESSION_COOKIE, "")
    if not hmac.compare_digest(expected, provided):
        return JSONResponse(status_code=401, content={"detail": "Local session required"})
    return await call_next(request)


@app.post("/api/session")
async def create_session(request: Request):
    passphrase = env_passphrase()
    if not passphrase:
        return {"mode": "open", "message": "No passphrase configured; local demo mode is active"}
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid session request") from exc
    if not hmac.compare_digest(str(payload.get("passphrase", "")), passphrase):
        raise HTTPException(401, "Invalid local passphrase")
    response = JSONResponse({"mode": "secured", "message": "Local session started"})
    response.set_cookie(SESSION_COOKIE, session_token(passphrase, "atm-sentinel-session"), httponly=True, samesite="lax")
    return response


@app.get("/")
def root():
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "docs": "/docs",
        "statement": "Prototype evidence organization and integrity tracking.",
    }


app.include_router(system.router)
app.include_router(cases.router)
app.include_router(videos.router)
app.include_router(jobs.router)
app.include_router(frames.router)
app.include_router(exports.router)
app.include_router(cv.router)
app.include_router(cv_enhancement.router)
