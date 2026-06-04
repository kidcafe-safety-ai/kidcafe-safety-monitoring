"""Health check route."""

from fastapi import APIRouter

from src.api.schemas import HealthResponse, success_response


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health():
    return success_response({"service": "kidcafe-api", "healthy": True})
