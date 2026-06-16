"""Current status API routes."""

from fastapi import APIRouter

from src.api import repositories
from src.api.schemas import (
    CurrentStatusCreate,
    CurrentStatusResponse,
    CurrentStatusUpdateResponse,
    success_response,
)


router = APIRouter()


@router.put("/status/current", response_model=CurrentStatusUpdateResponse)
def put_current_status(status: CurrentStatusCreate):
    return success_response(repositories.upsert_current_status(status))


@router.get("/status/current", response_model=CurrentStatusResponse)
def get_current_status():
    return success_response(repositories.get_current_status())
