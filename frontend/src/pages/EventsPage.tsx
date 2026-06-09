import { useCallback, useMemo, useState } from "react";
import { getEvents } from "../api/eventsApi";
import EventChart from "../components/EventChart";
import EventTable from "../components/EventTable";
import { usePolling } from "../hooks/usePolling";
import type { EventType, SafetyEvent } from "../types/event";

type EventFilter = "ALL" | EventType;

const FILTERS: EventFilter[] = ["ALL", "ENTER", "DWELL", "EXIT"];

export default function EventsPage() {
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [filter, setFilter] = useState<EventFilter>("ALL");
  const [isLoading, setIsLoading] = useState(true);
  const [hasApiError, setHasApiError] = useState(false);

  const loadEvents = useCallback(async () => {
    const response = await getEvents();
    setEvents(response.data);
    setHasApiError(response.status === "error");
    setIsLoading(false);
  }, []);

  usePolling(loadEvents, 5000);

  const filteredEvents = useMemo(() => {
    if (filter === "ALL") {
      return events;
    }

    return events.filter((event) => event.event_type === filter);
  }, [events, filter]);

  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <h1>이벤트 기록 / 통계</h1>
          <p>Event Schema v1 기반 이벤트 조회와 타입별 통계</p>
        </div>
      </div>

      <section className="card filter-card">
        <span>Event Type</span>
        <div className="segmented-control">
          {FILTERS.map((item) => (
            <button
              className={filter === item ? "active" : ""}
              key={item}
              onClick={() => setFilter(item)}
              type="button"
            >
              {item === "ALL" ? "전체" : item}
            </button>
          ))}
        </div>
      </section>

      {isLoading ? <div className="state-banner">데이터를 불러오는 중입니다.</div> : null}
      {hasApiError ? (
        <div className="state-banner error">
          API 연결에 실패했습니다. mock 또는 기본값으로 화면을 표시합니다.
        </div>
      ) : null}
      {!isLoading && filteredEvents.length === 0 ? (
        <div className="state-banner empty">표시할 이벤트가 없습니다.</div>
      ) : null}

      <section className="events-grid">
        <EventChart events={filteredEvents} />
        <EventTable events={filteredEvents} />
      </section>
    </main>
  );
}
