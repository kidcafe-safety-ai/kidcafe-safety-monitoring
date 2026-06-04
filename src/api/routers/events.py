"""Event API routes."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

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
):
    return success_response(
        repositories.list_events(
            limit=limit,
            offset=offset,
            event_type=event_type,
            zone_id=zone_id,
        )
    )


@router.get("/events/recent", response_model=EventRecentResponse)
def get_recent_events(limit: int = Query(default=10, ge=1, le=100)):
    return success_response(repositories.recent_events(limit=limit))
