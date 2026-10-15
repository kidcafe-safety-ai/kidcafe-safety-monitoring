import { useCallback, useEffect, useMemo, useState } from "react";
import { getEvents } from "../api/eventsApi";
import EventChart from "../components/EventChart";
import EventTable from "../components/EventTable";
import EventTimelineChart from "../components/EventTimelineChart";
import { usePolling, type PollingContext } from "../hooks/usePolling";
import type { EventType, SafetyEvent } from "../types/event";
import { getEventDisplayMeta, KNOWN_EVENT_TYPES } from "../utils/eventDisplay";

type EventFilter = "ALL" | EventType;

const FILTERS: EventFilter[] = ["ALL", ...KNOWN_EVENT_TYPES];
const PAGE_SIZE = 5;

export default function EventsPage() {
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [filter, setFilter] = useState<EventFilter>("ALL");
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [hasApiError, setHasApiError] = useState(false);

  const loadEvents = useCallback(async (context: PollingContext) => {
    const response = await getEvents({ signal: context.signal });

    if (!context.isActive()) {
      return;
    }

    if (response.status !== "error") {
      setEvents(response.data);
    }

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

  const totalPages = Math.ceil(filteredEvents.length / PAGE_SIZE);
  const safeCurrentPage =
    totalPages === 0 ? 0 : Math.min(Math.max(currentPage, 1), totalPages);
  const pageStart = safeCurrentPage > 0 ? (safeCurrentPage - 1) * PAGE_SIZE : 0;
  const paginatedEvents = filteredEvents.slice(pageStart, pageStart + PAGE_SIZE);

  useEffect(() => {
    if (totalPages === 0) {
      setCurrentPage(1);
      return;
    }

    setCurrentPage((page) => Math.min(Math.max(page, 1), totalPages));
  }, [totalPages]);

  const handleFilterChange = (nextFilter: EventFilter) => {
    setFilter(nextFilter);
    setCurrentPage(1);
  };

  const goToPreviousPage = () => {
    setCurrentPage((page) => Math.max(1, page - 1));
  };

  const goToNextPage = () => {
    setCurrentPage((page) =>
      totalPages === 0 ? 1 : Math.min(totalPages, page + 1),
    );
  };

  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>이벤트 기록 / 통계</h1>
            <span className="status-pill">안전 이벤트 현황</span>
          </div>
        </div>
      </div>

      <section className="card filter-card">
        <span>이벤트 유형</span>
        <div className="segmented-control">
          {FILTERS.map((item) => (
            <button
              className={filter === item ? "active" : ""}
              key={item}
              onClick={() => handleFilterChange(item)}
              type="button"
            >
              {item === "ALL" ? "전체" : getEventDisplayMeta(item).label}
            </button>
          ))}
        </div>
      </section>

      {isLoading ? <div className="state-banner">데이터를 불러오는 중입니다.</div> : null}
      {hasApiError ? (
        <div className="state-banner error">
          안전 이벤트 데이터를 불러오지 못했습니다. 표시된 기록은 마지막 정상 응답의 오래된 데이터일 수 있습니다.
        </div>
      ) : null}
      <section className="events-grid">
        <EventChart events={filteredEvents} />
        <EventTable
          events={paginatedEvents}
          totalCount={filteredEvents.length}
          pagination={{
            currentPage: safeCurrentPage,
            totalPages,
            onNext: goToNextPage,
            onPrevious: goToPreviousPage,
          }}
        />
        <EventTimelineChart events={filteredEvents} />
      </section>
    </main>
  );
}
