"""Zone 설정 조회·저장 route (Phase 4).

계약: docs/api_contract.md `GET /zones Phase 4 계약`, `PUT /zones Phase 4 저장 계약`
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.api import zone_store
from src.api.schemas import (
    ErrorResponse,
    PutZonesRequest,
    ZonesResponse,
    error_response,
    success_response,
)

router = APIRouter()


@router.get(
    "/zones",
    response_model=ZonesResponse,
    responses={500: {"model": ErrorResponse}},
)
def get_zones():
    """현재 Zone 설정을 version envelope로 반환한다.

    유효한 빈 파일은 `zones=[]`로 성공한다. 파일 누락·읽기 실패·JSON 또는
    schema 오류는 빈 Zone이나 Mock으로 대체하지 않고 500을 반환한다.
    """
    try:
        config = zone_store.load_zone_config()
    except zone_store.ZoneConfigUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_response(zone_store.UNAVAILABLE_MESSAGE),
        )

    return success_response(config.to_dict())


@router.put(
    "/zones",
    response_model=ZonesResponse,
    responses={
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def put_zones(request: PutZonesRequest):
    """전체 Zone 목록을 교체 저장한다.

    schema·polygon 오류는 Pydantic이 422로 처리한다. `expected_version`이
    현재 version과 다르면 409이며, Frontend는 자동으로 덮어쓰지 않고 최신
    설정을 재조회한 뒤 사용자에게 다시 확인받는다.
    """
    try:
        config = zone_store.save_zone_config(
            request.expected_version,
            [zone.model_dump() for zone in request.zones],
        )
    except zone_store.ZoneVersionConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_response(zone_store.CONFLICT_MESSAGE),
        )
    except zone_store.ZoneConfigUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_response(zone_store.UNAVAILABLE_MESSAGE),
        )
    except zone_store.ZoneSaveError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_response(zone_store.SAVE_FAILED_MESSAGE),
        )

    return success_response(config.to_dict())
