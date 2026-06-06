import type { SafetyEvent } from "../types/event";

interface EventTableProps {
  events: SafetyEvent[];
}

function formatTime(timestamp: string) {
  return timestamp;
}

export default function EventTable({ events }: EventTableProps) {
  return (
    <section className="card table-card">
      <div className="panel-header">
        <h2>이벤트 테이블</h2>
        <span>{events.length}건</span>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>시간</th>
              <th>이벤트</th>
              <th>추적 ID</th>
              <th>구역</th>
              <th>프레임</th>
              <th>영상 소스</th>
              <th>위험도</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.event_id}>
                <td>{formatTime(event.timestamp)}</td>
                <td>
                  <span className={`type-badge type-${event.event_type.toLowerCase()}`}>
                    {event.event_type}
                  </span>
                </td>
                <td>{event.track_id}</td>
                <td>{event.zone_id}</td>
                <td>{event.frame_number}</td>
                <td>{event.video_source}</td>
                <td>{event.severity ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
