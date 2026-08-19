import type { SafetyEvent, Severity } from "../types/event";
import {
  formatEventCause,
  formatEventZone,
  getEventDisplayMeta,
  getEventSeverity,
  KNOWN_EVENT_TYPES,
} from "./eventDisplay";

export interface ReportTypeCount {
  eventType: string;
  label: string;
  count: number;
}

export interface ReportZoneCount {
  zoneKey: string;
  label: string;
  count: number;
}

export interface ReportFallSuspectItem {
  eventId: string;
  trackLabel: string;
  zoneLabel: string;
  causeText: string;
}

export interface ReportAggregation {
  totalEvents: number;
  fallSuspectCount: number;
  highSeverityCount: number;
  dangerZoneEventCount: number;
  eventTypeCounts: ReportTypeCount[];
  zoneCounts: ReportZoneCount[];
  fallSuspectItems: ReportFallSuspectItem[];
}

function getDerivedSeverity(event: SafetyEvent): Severity | null {
  return getEventSeverity(event.event_type, event.severity);
}

function isDangerZoneRelated(event: SafetyEvent) {
  return event.zone_type === "danger" || event.event_type === "DANGER_ZONE_DWELL";
}

function getZoneKey(event: SafetyEvent) {
  const zoneLabel = formatEventZone(event);

  return event.zone_id.trim() || zoneLabel;
}

function sortByCountDescThenLabel<T extends { count: number; label: string }>(
  items: T[],
) {
  return [...items].sort((a, b) => {
    if (b.count !== a.count) {
      return b.count - a.count;
    }

    return a.label.localeCompare(b.label, "ko");
  });
}

export function aggregateReportEvents(events: SafetyEvent[]): ReportAggregation {
  const typeCounts = new Map<string, number>();
  const zoneCounts = new Map<string, { label: string; count: number }>();

  events.forEach((event) => {
    typeCounts.set(event.event_type, (typeCounts.get(event.event_type) ?? 0) + 1);

    const zoneKey = getZoneKey(event);
    const zoneLabel = formatEventZone(event);
    const zoneCount = zoneCounts.get(zoneKey) ?? { label: zoneLabel, count: 0 };
    zoneCounts.set(zoneKey, {
      label: zoneCount.label,
      count: zoneCount.count + 1,
    });
  });

  const knownTypeSet = new Set<string>(KNOWN_EVENT_TYPES);
  const unknownTypes = Array.from(typeCounts.keys()).filter(
    (eventType) => !knownTypeSet.has(eventType),
  );
  const eventTypes = [...KNOWN_EVENT_TYPES, ...unknownTypes];
  const eventTypeCounts = eventTypes
    .map((eventType) => ({
      eventType,
      label: getEventDisplayMeta(eventType).label,
      count: typeCounts.get(eventType) ?? 0,
    }))
    .filter((item) => item.count > 0);

  return {
    totalEvents: events.length,
    fallSuspectCount: events.filter((event) => event.event_type === "FALL_SUSPECT")
      .length,
    highSeverityCount: events.filter((event) => getDerivedSeverity(event) === "HIGH")
      .length,
    dangerZoneEventCount: events.filter(isDangerZoneRelated).length,
    eventTypeCounts,
    zoneCounts: sortByCountDescThenLabel(
      Array.from(zoneCounts.entries()).map(([zoneKey, value]) => ({
        zoneKey,
        label: value.label,
        count: value.count,
      })),
    ),
    fallSuspectItems: events
      .filter((event) => event.event_type === "FALL_SUSPECT")
      .map((event) => ({
        eventId: event.event_id,
        trackLabel: `Track #${event.track_id}`,
        zoneLabel: formatEventZone(event),
        causeText: formatEventCause(event.cause),
      })),
  };
}
