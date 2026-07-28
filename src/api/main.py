"""FastAPI entry point for the KidCafe Safety AI backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.database import init_db
from src.api.routers import events, health, live, status, summary, zones


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="KidCafe Safety API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(409)
async def conflict_exception_handler(request: Request, exc):
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return JSONResponse(status_code=409, content=detail)
    return JSONResponse(
        status_code=409,
        content={"status": "error", "data": None, "message": "conflict"},
    )


app.include_router(health.router)
app.include_router(events.router)
app.include_router(status.router)
app.include_router(live.router)
app.include_router(summary.router)
app.include_router(zones.router)
