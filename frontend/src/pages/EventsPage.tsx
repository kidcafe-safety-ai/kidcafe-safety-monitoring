import { useEffect, useMemo, useState } from "react";
import { getEvents } from "../api/eventsApi";
import EventChart from "../components/EventChart";
import EventTable from "../components/EventTable";
import type { EventType, SafetyEvent } from "../types/event";

type EventFilter = "ALL" | EventType;

const FILTERS: EventFilter[] = ["ALL", "ENTER", "DWELL", "EXIT"];

export default function EventsPage() {
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [filter, setFilter] = useState<EventFilter>("ALL");

  useEffect(() => {
    async function loadEvents() {
      const response = await getEvents();
      setEvents(response.data);
    }

    loadEvents();
  }, []);

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

      <section className="events-grid">
        <EventChart events={filteredEvents} />
        <EventTable events={filteredEvents} />
      </section>
    </main>
  );
}
