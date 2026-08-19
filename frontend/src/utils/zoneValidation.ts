import type { Zone, ZonePoint, ZoneType } from "../types/zoneSettings";

export interface ZoneValidationIssue {
  zoneIndex: number;
  field: string;
  message: string;
}

const ZONE_TYPES: readonly ZoneType[] = ["play", "exit", "restricted", "danger"];
const EPSILON = 1e-9;

function isFiniteNumber(value: number) {
  return Number.isFinite(value) && !Number.isNaN(value);
}

function pointKey([x, y]: ZonePoint) {
  return `${x},${y}`;
}

function polygonArea(points: ZonePoint[]) {
  if (points.length < 3) {
    return 0;
  }

  let area = 0;

  points.forEach(([x1, y1], index) => {
    const [x2, y2] = points[(index + 1) % points.length];
    area += x1 * y2 - x2 * y1;
  });

  return Math.abs(area) / 2;
}

function orientation(a: ZonePoint, b: ZonePoint, c: ZonePoint) {
  const value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1]);

  if (Math.abs(value) < EPSILON) {
    return 0;
  }

  return value > 0 ? 1 : 2;
}

function onSegment(a: ZonePoint, b: ZonePoint, c: ZonePoint) {
  return (
    b[0] <= Math.max(a[0], c[0]) + EPSILON &&
    b[0] + EPSILON >= Math.min(a[0], c[0]) &&
    b[1] <= Math.max(a[1], c[1]) + EPSILON &&
    b[1] + EPSILON >= Math.min(a[1], c[1])
  );
}

function segmentsIntersect(
  p1: ZonePoint,
  q1: ZonePoint,
  p2: ZonePoint,
  q2: ZonePoint,
) {
  const o1 = orientation(p1, q1, p2);
  const o2 = orientation(p1, q1, q2);
  const o3 = orientation(p2, q2, p1);
  const o4 = orientation(p2, q2, q1);

  if (o1 !== o2 && o3 !== o4) {
    return true;
  }

  return (
    (o1 === 0 && onSegment(p1, p2, q1)) ||
    (o2 === 0 && onSegment(p1, q2, q1)) ||
    (o3 === 0 && onSegment(p2, p1, q2)) ||
    (o4 === 0 && onSegment(p2, q1, q2))
  );
}

function hasSelfIntersection(points: ZonePoint[]) {
  if (points.length < 4) {
    return false;
  }

  for (let i = 0; i < points.length; i += 1) {
    const a1 = points[i];
    const a2 = points[(i + 1) % points.length];

    for (let j = i + 1; j < points.length; j += 1) {
      const b1 = points[j];
      const b2 = points[(j + 1) % points.length];
      const sharesVertex =
        i === j ||
        (i + 1) % points.length === j ||
        i === (j + 1) % points.length;

      if (sharesVertex) {
        continue;
      }

      if (segmentsIntersect(a1, a2, b1, b2)) {
        return true;
      }
    }
  }

  return false;
}

function addIssue(
  issues: ZoneValidationIssue[],
  zoneIndex: number,
  field: string,
  message: string,
) {
  issues.push({ zoneIndex, field, message });
}

export function validateZones(zones: Zone[]) {
  const issues: ZoneValidationIssue[] = [];
  const zoneIds = new Map<string, number>();

  zones.forEach((zone, zoneIndex) => {
    const zoneId = zone.zone_id.trim();
    const zoneName = zone.zone_name.trim();

    if (zoneId.length === 0) {
      addIssue(issues, zoneIndex, "zone_id", "zone_id는 비워둘 수 없습니다.");
    } else if (zoneIds.has(zoneId)) {
      addIssue(issues, zoneIndex, "zone_id", "zone_id가 중복되었습니다.");
      addIssue(
        issues,
        zoneIds.get(zoneId) ?? zoneIndex,
        "zone_id",
        "zone_id가 중복되었습니다.",
      );
    } else {
      zoneIds.set(zoneId, zoneIndex);
    }

    if (zoneName.length === 0) {
      addIssue(issues, zoneIndex, "zone_name", "zone_name은 비워둘 수 없습니다.");
    }

    if (zone.type !== "polygon") {
      addIssue(issues, zoneIndex, "type", "type은 polygon이어야 합니다.");
    }

    if (!ZONE_TYPES.includes(zone.zone_type)) {
      addIssue(issues, zoneIndex, "zone_type", "지원하지 않는 zone_type입니다.");
    }

    if (zone.points.length < 3) {
      addIssue(issues, zoneIndex, "points", "points는 최소 3개 이상이어야 합니다.");
    }

    const seenPoints = new Set<string>();

    zone.points.forEach(([x, y], pointIndex) => {
      const field = `points.${pointIndex}`;

      if (!isFiniteNumber(x) || !isFiniteNumber(y)) {
        addIssue(issues, zoneIndex, field, "좌표는 NaN/Infinity가 아닌 숫자여야 합니다.");
      }

      if (x < 0 || x > 1 || y < 0 || y > 1) {
        addIssue(issues, zoneIndex, field, "좌표 x, y는 0.0 이상 1.0 이하여야 합니다.");
      }

      const key = pointKey([x, y]);

      if (seenPoints.has(key)) {
        addIssue(issues, zoneIndex, "points", "중복 좌표가 포함되어 있습니다.");
      }

      seenPoints.add(key);
    });

    if (zone.points.length >= 3 && polygonArea(zone.points) <= EPSILON) {
      addIssue(issues, zoneIndex, "points", "polygon 면적이 0입니다.");
    }

    if (hasSelfIntersection(zone.points)) {
      addIssue(issues, zoneIndex, "points", "self-intersection polygon은 저장할 수 없습니다.");
    }

    const dwellThreshold = zone.rules.dwell_threshold_sec;

    if (
      !Number.isInteger(dwellThreshold) ||
      dwellThreshold < 0 ||
      dwellThreshold > 3600
    ) {
      addIssue(
        issues,
        zoneIndex,
        "rules.dwell_threshold_sec",
        "dwell_threshold_sec는 0 이상 3600 이하 정수여야 합니다.",
      );
    }
  });

  return issues;
}
