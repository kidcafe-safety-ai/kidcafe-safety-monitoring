import type { EventCause, EventType, SafetyEvent, Severity } from "../types/event";

export interface EventDisplayMeta {
  type: string;
  label: string;
  description: string;
  severity: Severity | null;
  severityLabel: string;
  iconLabel: string;
  badgeClass: string;
  barClass: string;
}

export const KNOWN_EVENT_TYPES = [
  "ENTER",
  "DWELL",
  "EXIT",
  "ENTER_RESTRICTED",
  "DANGER_ZONE_DWELL",
  "FALL_SUSPECT",
] as const;

type KnownDisplayEventType = (typeof KNOWN_EVENT_TYPES)[number];

const EVENT_DISPLAY_META: Record<KnownDisplayEventType, EventDisplayMeta> = {
  ENTER: {
    type: "ENTER",
    label: "진입",
    description: "구역 진입 이벤트",
    severity: "LOW",
    severityLabel: "낮음",
    iconLabel: "진입",
    badgeClass: "type-enter",
    barClass: "bar-enter",
  },
  DWELL: {
    type: "DWELL",
    label: "체류",
    description: "구역 체류 이벤트",
    severity: "LOW",
    severityLabel: "낮음",
    iconLabel: "체류",
    badgeClass: "type-dwell",
    barClass: "bar-dwell",
  },
  EXIT: {
    type: "EXIT",
    label: "이탈",
    description: "구역 이탈 이벤트",
    severity: "LOW",
    severityLabel: "낮음",
    iconLabel: "이탈",
    badgeClass: "type-exit",
    barClass: "bar-exit",
  },
  ENTER_RESTRICTED: {
    type: "ENTER_RESTRICTED",
    label: "제한구역 진입",
    description: "제한구역에 진입한 안전 이벤트",
    severity: "HIGH",
    severityLabel: "높음",
    iconLabel: "제한",
    badgeClass: "type-enter-restricted",
    barClass: "bar-enter-restricted",
  },
  DANGER_ZONE_DWELL: {
    type: "DANGER_ZONE_DWELL",
    label: "위험구역 체류",
    description: "위험구역에 기준 시간 이상 체류한 안전 이벤트",
    severity: "HIGH",
    severityLabel: "높음",
    iconLabel: "위험",
    badgeClass: "type-danger-zone-dwell",
    barClass: "bar-danger-zone-dwell",
  },
  FALL_SUSPECT: {
    type: "FALL_SUSPECT",
    label: "낙상 의심",
    description: "낙상 가능성이 감지된 안전 이벤트",
    severity: "HIGH",
    severityLabel: "높음",
    iconLabel: "낙상",
    badgeClass: "type-fall-suspect",
    barClass: "bar-fall-suspect",
  },
};

function isKnownEventType(
  eventType: EventType | string,
): eventType is KnownDisplayEventType {
  return KNOWN_EVENT_TYPES.includes(eventType as KnownDisplayEventType);
}

export function getEventDisplayMeta(eventType: EventType | string): EventDisplayMeta {
  if (isKnownEventType(eventType)) {
    return EVENT_DISPLAY_META[eventType];
  }

  return {
    type: eventType,
    label: "알 수 없는 이벤트",
    description: "정의되지 않은 이벤트 타입",
    severity: null,
    severityLabel: "확인 필요",
    iconLabel: "기타",
    badgeClass: "type-unknown",
    barClass: "bar-unknown",
  };
}

export function getEventSeverity(
  eventType: EventType | string,
  fallback?: Severity,
) {
  return getEventDisplayMeta(eventType).severity ?? fallback ?? null;
}

export function getSeverityDisplay(severity: Severity | string | null | undefined) {
  if (severity === "HIGH") {
    return {
      label: "높음",
      iconLabel: "긴급",
      className: "risk-high",
      ariaLabel: "위험도 높음",
    };
  }

  if (severity === "MEDIUM") {
    return {
      label: "중간",
      iconLabel: "주의",
      className: "risk-medium",
      ariaLabel: "위험도 중간",
    };
  }

  if (severity === "LOW") {
    return {
      label: "낮음",
      iconLabel: "낮음",
      className: "risk-low",
      ariaLabel: "위험도 낮음",
    };
  }

  return {
    label: "확인 필요",
    iconLabel: "확인",
    className: "risk-unknown",
    ariaLabel: "위험도 확인 필요",
  };
}

export function formatEventZone(event: SafetyEvent) {
  if (event.zone_name && event.zone_name.trim().length > 0) {
    return event.zone_name.trim();
  }

  const zoneId = event.zone_id.trim();
  const normalizedZoneId = zoneId.toLowerCase();

  if (normalizedZoneId === "global" || normalizedZoneId === "__global__") {
    return "전체 구역";
  }

  return zoneId || "Zone 정보 없음";
}

export function formatTrackId(trackId: number | null | undefined) {
  return typeof trackId === "number" && Number.isFinite(trackId) && trackId >= 0
    ? `Track #${trackId}`
    : "Track 정보 없음";
}

export function formatEventCause(cause: EventCause | null | undefined) {
  if (cause?.type === "NEARBY_TRACK") {
    return `외부 접촉 의심 · Track #${cause.track_id}`;
  }

  return "원인 후보 없음";
}
