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

function navigateToEvents(eventId: string) {
  window.dispatchEvent(
    new CustomEvent("kidcafe:navigate", {
      detail: {
        page: "events",
        eventId,
      },
    }),
  );
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
    if (isLoading) {
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
  }, [events, isLoading]);

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
          최근 이벤트 API 연결에 실패했습니다.
        </div>
      );
    }

    if (events.length === 0) {
      return (
        <div className="state-banner empty">표시할 최근 이벤트가 없습니다.</div>
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
              onClick={() => navigateToEvents(event.event_id)}
              type="button"
            >
              <div className="event-summary">
                <strong>{formatOccurredAt(event)}</strong>
                <p>{meta.description}</p>
                <span className="recent-event-zone">{formatEventZone(event)}</span>
                {causeText ? (
                  <span className="recent-event-cause">{causeText}</span>
                ) : null}
              </div>
              <div className="event-meta">
                <span className={`type-badge ${meta.badgeClass}`}>
                  {meta.label}
                </span>
                <span
                  aria-label={severityDisplay.ariaLabel}
                  className={`risk-badge ${severityDisplay.className}`}
                >
                  {severityDisplay.iconLabel} · {severityDisplay.label}
                </span>
                <span className="track-id">{formatTrackId(event.track_id)}</span>
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
