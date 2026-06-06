import type { SafetyEvent } from "../types/event";

interface RecentEventListProps {
  events: SafetyEvent[];
}

function formatTime(timestamp: string) {
  return timestamp;
}

export default function RecentEventList({ events }: RecentEventListProps) {
  return (
    <section className="card panel recent-events-panel">
      <div className="panel-header">
        <h2>최근 이벤트</h2>
        <span>{events.length}건</span>
      </div>
      <div className="event-list">
        {events.map((event) => (
          <article className="event-list-item" key={event.event_id}>
            <div className="event-summary">
              <strong>{formatTime(event.timestamp)}</strong>
              <p>{event.event_label ?? event.event_type}</p>
            </div>
            <div className="event-meta">
              <span className={`type-badge type-${event.event_type.toLowerCase()}`}>
                {event.event_type}
              </span>
              <span className="track-id">Track {event.track_id}</span>
              <span className="zone-id">{event.zone_id}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
