"""Event API routes."""

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import AfterValidator

from src.api import repositories
from src.api.schemas import (
    ErrorResponse,
    EventCreate,
    EventListResponse,
    EventRecentResponse,
    EventResponse,
    EventType,
    error_response,
    success_response,
)

router = APIRouter()


def _require_timezone(value: Optional[datetime]) -> Optional[datetime]:
    """기간 입력은 timezone을 포함해야 한다 (docs/api_contract.md GET /events)."""
    if value is not None and value.tzinfo is None:
        raise ValueError("timezone is required")
    return value


# Query()를 Annotated 안에 둔다. `= Query(...)` 형태로 기본값을 주면 FastAPI가
# Annotated의 AfterValidator를 사용하지 않아 naive datetime이 그대로 통과한다.
AwareDatetime = Annotated[Optional[datetime], AfterValidator(_require_timezone), Query()]


@router.post(
    "/events",
    status_code=status.HTTP_201_CREATED,
    response_model=EventResponse,
    responses={409: {"model": ErrorResponse}},
)
def post_event(event: EventCreate):
    try:
        created_event = repositories.create_event(event)
    except repositories.DuplicateEventError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_response("event_id already exists"),
        )

    return success_response(created_event)


@router.get("/events", response_model=EventListResponse)
def get_events(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    event_type: Optional[EventType] = None,
    zone_id: Optional[str] = None,
    created_from: AwareDatetime = None,
    created_to: AwareDatetime = None,
):
    """이벤트 목록 조회. 기간 필터는 하위 호환 방식의 선택 필드다.

    `created_from` 이상, `created_to` 미만을 조회한다. 두 값 모두 timezone을
    포함한 RFC 3339여야 하고 `created_from < created_to`여야 한다.
    """
    if created_from is not None and created_to is not None and created_from >= created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["query", "created_to"],
                    "msg": "Value error, created_to must be later than created_from",
                    "input": created_to.isoformat(),
                }
            ],
        )

    return success_response(
        repositories.list_events(
            limit=limit,
            offset=offset,
            event_type=event_type,
            zone_id=zone_id,
            created_from=created_from,
            created_to=created_to,
        )
    )


@router.get("/events/recent", response_model=EventRecentResponse)
def get_recent_events(
    limit: int = Query(default=10, ge=1, le=100),
    minutes: Optional[int] = Query(default=None, ge=1, le=1440),
):
    return success_response(repositories.recent_events(limit=limit, minutes=minutes))
