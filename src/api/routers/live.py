"""Live View latest-frame API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse

from src.api.live_frame_store import live_frame_store
from src.api.schemas import ApiResponse, error_response, success_response


MAX_LIVE_FRAME_BYTES = 1024 * 1024
JPEG_CONTENT_TYPE = "image/jpeg"

router = APIRouter()


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_response(message))


def _is_jpeg_bytes(body: bytes) -> bool:
    return len(body) >= 4 and body.startswith(b"\xff\xd8") and body.endswith(b"\xff\xd9")


def _normalize_captured_at(value: str) -> str:
    raw_value = value.strip()
    if not raw_value:
        raise ValueError("captured_at is required")

    parse_value = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    try:
        parsed = datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO 8601 datetime") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")

    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.put(
    "/live/frame",
    response_model=ApiResponse,
    responses={
        413: {"description": "Payload Too Large"},
        415: {"description": "Unsupported Media Type"},
        422: {"description": "Invalid metadata"},
    },
)
async def put_live_frame(
    request: Request,
    source: str = Query(..., min_length=1),
    frame_number: int = Query(..., ge=0),
    captured_at: str = Query(...),
):
    if request.headers.get("content-type", "").lower() != JPEG_CONTENT_TYPE:
        return _error(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "content-type must be image/jpeg",
        )

    body = await request.body()
    if not body:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "body must not be empty")
    if len(body) > MAX_LIVE_FRAME_BYTES:
        return _error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "jpeg payload too large")
    if not _is_jpeg_bytes(body):
        return _error(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "body must be jpeg binary")
    cleaned_source = source.strip()
    if not cleaned_source:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "source must not be empty")

    try:
        normalized_captured_at = _normalize_captured_at(captured_at)
    except ValueError as exc:
        return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    live_frame_store.put_frame(
        jpeg_bytes=body,
        source=cleaned_source,
        frame_number=frame_number,
        captured_at=normalized_captured_at,
    )
    return success_response(
        {
            "source": cleaned_source,
            "frame_number": frame_number,
            "stored": True,
        }
    )


@router.get(
    "/live/frame",
    responses={
        200: {
            "description": "Latest JPEG frame",
            "content": {JPEG_CONTENT_TYPE: {}},
        },
        204: {"description": "No current frame"},
    },
)
def get_live_frame():
    frame = live_frame_store.get_frame()
    if frame is None:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"Cache-Control": "no-store"},
        )

    return Response(
        content=frame.jpeg_bytes,
        media_type=JPEG_CONTENT_TYPE,
        headers={
            "Cache-Control": "no-store",
            "X-Source": frame.source,
            "X-Frame-Number": str(frame.frame_number),
            "X-Captured-At": frame.captured_at,
        },
    )
