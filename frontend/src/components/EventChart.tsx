import type { EventType, SafetyEvent } from "../types/event";

interface EventChartProps {
  events: SafetyEvent[];
}

const EVENT_TYPES: EventType[] = ["ENTER", "DWELL", "EXIT"];

export default function EventChart({ events }: EventChartProps) {
  const counts = EVENT_TYPES.map((type) => ({
    type,
    count: events.filter((event) => event.event_type === type).length,
  }));
  const maxCount = Math.max(...counts.map((item) => item.count), 1);

  return (
    <section className="card panel">
      <div className="panel-header">
        <h2>이벤트 타입별 발생 수</h2>
        <span>Bar Chart</span>
      </div>
      <div className="bar-chart" aria-label="이벤트 타입별 발생 수 Bar Chart">
        {counts.map((item) => (
          <div className="bar-row" key={item.type}>
            <span className="bar-label">{item.type}</span>
            <div className="bar-track">
              <div
                className={`bar-fill bar-${item.type.toLowerCase()}`}
                style={{ width: `${(item.count / maxCount) * 100}%` }}
              />
            </div>
            <strong>{item.count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
