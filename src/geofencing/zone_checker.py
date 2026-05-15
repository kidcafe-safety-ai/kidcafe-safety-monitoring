"""Track이 Zone 내부에 있는지 판정."""

from typing import Dict, List

from shapely.geometry import Point, Polygon

from src.common.types import Track, Zone


class ZoneChecker:
    """Track의 발 위치가 어느 Zone 안에 있는지 판정."""

    def __init__(self, zones: List[Zone], frame_width: int, frame_height: int):
        self.zones = zones
        self.frame_width = frame_width
        self.frame_height = frame_height

        self.polygons: Dict[str, Polygon] = {}
        for z in zones:
            if z.type == "polygon":
                self.polygons[z.zone_id] = Polygon(z.points)

    def check(self, track: Track) -> List[str]:
        """
        Track의 발 위치가 들어있는 zone_id 리스트 반환.

        - 픽셀 좌표 → 정규화 좌표(0~1) 변환
        - shapely.covers()로 경계 포함 판정
        """
        foot_x, foot_y = track.foot_point
        norm_x = foot_x / self.frame_width
        norm_y = foot_y / self.frame_height
        point = Point(norm_x, norm_y)

        zones_in = []
        for zone_id, polygon in self.polygons.items():
            if polygon.covers(point):
                zones_in.append(zone_id)

        return zones_in