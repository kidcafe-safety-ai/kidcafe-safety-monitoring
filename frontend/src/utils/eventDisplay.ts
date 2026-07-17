import type { EventCause, EventType, Severity } from "../types/event";

export interface EventDisplayMeta {
  type: string;
  label: string;
  description: string;
  severity: Severity | null;
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
    badgeClass: "type-enter",
    barClass: "bar-enter",
  },
  DWELL: {
    type: "DWELL",
    label: "체류",
    description: "구역 체류 이벤트",
    severity: "LOW",
    badgeClass: "type-dwell",
    barClass: "bar-dwell",
  },
  EXIT: {
    type: "EXIT",
    label: "이탈",
    description: "구역 이탈 이벤트",
    severity: "LOW",
    badgeClass: "type-exit",
    barClass: "bar-exit",
  },
  ENTER_RESTRICTED: {
    type: "ENTER_RESTRICTED",
    label: "제한구역 진입",
    description: "제한구역에 진입한 안전 이벤트",
    severity: "HIGH",
    badgeClass: "type-enter-restricted",
    barClass: "bar-enter-restricted",
  },
  DANGER_ZONE_DWELL: {
    type: "DANGER_ZONE_DWELL",
    label: "위험구역 체류",
    description: "위험구역에 기준 시간 이상 체류한 안전 이벤트",
    severity: "HIGH",
    badgeClass: "type-danger-zone-dwell",
    barClass: "bar-danger-zone-dwell",
  },
  FALL_SUSPECT: {
    type: "FALL_SUSPECT",
    label: "낙상 의심",
    description: "낙상 가능성이 감지된 안전 이벤트",
    severity: "HIGH",
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
    label: eventType,
    description: "정의되지 않은 이벤트 타입",
    severity: null,
    badgeClass: "type-unknown",
    barClass: "bar-unknown",
  };
}

export function formatEventCause(cause: EventCause | null | undefined) {
  if (cause?.type === "NEARBY_TRACK") {
    return `외부 접촉 의심 · Track #${cause.track_id}`;
  }

  return "원인 후보 없음";
}
