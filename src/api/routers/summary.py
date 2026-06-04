"""Summary KPI route."""

from fastapi import APIRouter

from src.api.repositories import get_summary
from src.api.schemas import SummaryResponse, success_response


router = APIRouter()


@router.get("/summary", response_model=SummaryResponse)
def read_summary():
    return success_response(get_summary())
