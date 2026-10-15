"""FastAPI entry point for the KidCafe Safety AI backend."""

from __future__ import annotations

import math
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

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


@app.exception_handler(StarletteHTTPException)
async def envelope_exception_handler(request: Request, exc: StarletteHTTPException):
    """`detail`이 envelope dict면 그대로, 아니면 FastAPI 기본 형식으로 반환한다.

    409(중복 event_id, Zone version 충돌)와 500(Zone 설정 조회·저장 실패)이
    `{"status", "data", "message"}` envelope를 쓴다.

    상태 코드별 handler를 등록하지 않는 이유: Starlette에서 500은
    ServerErrorMiddleware가 미처리 예외용으로 선점하고 있어
    `HTTPException(500)`이 그 handler로 오지 않는다. `HTTPException` 자체에
    붙여야 코드와 무관하게 동작한다.

    Pydantic 검증 실패(422)는 `RequestValidationError`라 여기로 오지 않고
    기존 `detail` 배열 형식을 유지한다.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return await http_exception_handler(request, exc)


def _replace_non_finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, list):
        return [_replace_non_finite(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_non_finite(item) for key, item in value.items()}
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """FastAPI 기본 422 형식(`{"detail": [...]}`)을 유지한다.

    기본 handler는 `detail[].input`에 요청 값을 그대로 담는데, NaN·Infinity가
    들어 있으면 JSON 직렬화가 실패해 422 대신 500이 나간다. 그런 값만 문자열
    (`"nan"`, `"inf"`)로 바꿔 422를 보장한다.
    """
    return JSONResponse(
        status_code=422,
        content={"detail": _replace_non_finite(jsonable_encoder(exc.errors()))},
    )


app.include_router(health.router)
app.include_router(events.router)
app.include_router(status.router)
app.include_router(live.router)
app.include_router(summary.router)
app.include_router(zones.router)
