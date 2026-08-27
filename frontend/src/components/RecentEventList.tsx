import { useEffect, useRef, useState } from "react";
import type { SafetyEvent } from "../types/event";
import {
  formatEventCause,
  formatEventZone,
  formatTrackId,
  getEventDisplayMeta,
  getEventSeverity,
  getSeverityDisplay,
} from "../utils/eventDisplay";
import {
  formatSeoulDateTimeDisplay,
  parseUtcTimestamp,
} from "../utils/eventDateTime";

interface RecentEventListProps {
  events: SafetyEvent[];
  isLoading?: boolean;
  hasError?: boolean;
}

const HIGH_HIGHLIGHT_DURATION_MS = 2400;
const MAX_SEEN_EVENT_IDS = 500;

function formatOccurredAt(event: SafetyEvent) {
  const createdAtDate = parseUtcTimestamp(event.created_at);

  if (createdAtDate !== null) {
    return formatSeoulDateTimeDisplay(createdAtDate);
  }

  return event.timestamp ? `영상 시각 ${event.timestamp}` : "발생 시각 확인 불가";
}

function navigateToAlertHistory(eventId: string) {
  window.dispatchEvent(
    new CustomEvent("kidcafe:navigate", {
      detail: {
        page: "alert-history",
        eventId,
      },
    }),
  );
}

function getRecentEventMessage(event: SafetyEvent) {
  if (event.event_type === "FALL_SUSPECT") {
    return "넘어짐 의심 상황이 감지되었습니다.";
  }

  if (event.event_type === "ENTER_RESTRICTED") {
    return "제한구역 접근이 감지되었습니다.";
  }

  if (event.event_type === "DANGER_ZONE_DWELL") {
    return "위험구역 체류 상황이 감지되었습니다.";
  }

  if (event.event_type === "ENTER") {
    return "아동의 구역 입장이 감지되었습니다.";
  }

  if (event.event_type === "DWELL") {
    return "아동이 구역에 머무르고 있습니다.";
  }

  if (event.event_type === "EXIT") {
    return "아동이 구역을 벗어났습니다.";
  }

  return getEventDisplayMeta(event.event_type).description;
}

export default function RecentEventList({
  events,
  hasError = false,
  isLoading = false,
}: RecentEventListProps) {
  const [highlightedEventIds, setHighlightedEventIds] = useState<Set<string>>(
    () => new Set(),
  );
  const initializedRef = useRef(false);
  const seenEventIdsRef = useRef(new Set<string>());
  const seenEventIdQueueRef = useRef<string[]>([]);
  const highlightTimersRef = useRef<number[]>([]);

  useEffect(() => {
    if (isLoading || hasError) {
      return;
    }

    const rememberEventId = (eventId: string) => {
      if (seenEventIdsRef.current.has(eventId)) {
        return;
      }

      seenEventIdsRef.current.add(eventId);
      seenEventIdQueueRef.current.push(eventId);

      while (seenEventIdQueueRef.current.length > MAX_SEEN_EVENT_IDS) {
        const oldestEventId = seenEventIdQueueRef.current.shift();

        if (oldestEventId) {
          seenEventIdsRef.current.delete(oldestEventId);
        }
      }
    };

    if (!initializedRef.current) {
      events.forEach((event) => rememberEventId(event.event_id));
      initializedRef.current = true;
      return;
    }

    const newHighEventIds = events
      .filter((event) => {
        const severity = getEventSeverity(event.event_type, event.severity);
        return severity === "HIGH" && !seenEventIdsRef.current.has(event.event_id);
      })
      .map((event) => event.event_id);

    events.forEach((event) => rememberEventId(event.event_id));

    if (newHighEventIds.length === 0) {
      return;
    }

    setHighlightedEventIds((previous) => {
      const next = new Set(previous);
      newHighEventIds.forEach((eventId) => next.add(eventId));
      return next;
    });

    const timerId = window.setTimeout(() => {
      setHighlightedEventIds((previous) => {
        const next = new Set(previous);
        newHighEventIds.forEach((eventId) => next.delete(eventId));
        return next;
      });
    }, HIGH_HIGHLIGHT_DURATION_MS);

    highlightTimersRef.current.push(timerId);
  }, [events, hasError, isLoading]);

  useEffect(
    () => () => {
      highlightTimersRef.current.forEach((timerId) => window.clearTimeout(timerId));
      highlightTimersRef.current = [];
    },
    [],
  );

  const renderContent = () => {
    if (isLoading) {
      return <div className="state-banner">최근 이벤트를 불러오는 중입니다.</div>;
    }

    if (hasError) {
      return (
        <div className="state-banner error">
          최근 안전 이벤트를 불러오지 못했습니다. 연결 상태를 확인해 주세요.
        </div>
      );
    }

    if (events.length === 0) {
      return (
        <div className="state-banner empty">현재 감지된 최근 안전 이벤트가 없습니다.</div>
      );
    }

    return (
      <div className="event-list">
        {events.map((event) => {
          const meta = getEventDisplayMeta(event.event_type);
          const severity = getEventSeverity(event.event_type, event.severity);
          const severityDisplay = getSeverityDisplay(severity);
          const isHighlighted = highlightedEventIds.has(event.event_id);
          const causeText =
            event.event_type === "FALL_SUSPECT"
              ? formatEventCause(event.cause)
              : null;

          return (
            <button
              aria-label={`${meta.label} 이벤트 상세 보기`}
              className={`event-list-item recent-event-button ${
                isHighlighted ? "high-event-highlight" : ""
              }`}
              key={event.event_id}
              onClick={() => navigateToAlertHistory(event.event_id)}
              type="button"
            >
              <div className="recent-event-badge-row">
                <span className={`type-badge ${meta.badgeClass}`}>
                  {meta.label}
                </span>
                <span
                  aria-label={severityDisplay.ariaLabel}
                  className={`risk-badge ${severityDisplay.className}`}
                >
                  {severityDisplay.iconLabel} · {severityDisplay.label}
                </span>
              </div>
              <div className="event-summary">
                <strong>{getRecentEventMessage(event)}</strong>
                <span className="recent-event-time">{formatOccurredAt(event)}</span>
                <span className="recent-event-meta-row">
                  <span>{formatEventZone(event)}</span>
                  <span>{formatTrackId(event.track_id)}</span>
                </span>
                {causeText ? (
                  <span className="recent-event-cause">{causeText}</span>
                ) : null}
              </div>
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <section className="card panel recent-events-panel">
      <div className="panel-header">
        <h2>최근 안전 이벤트</h2>
        <span>{events.length}건</span>
      </div>
      {renderContent()}
    </section>
  );
}
