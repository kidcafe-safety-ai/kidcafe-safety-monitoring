import type { EventType, SafetyEvent } from "../types/event";
import { getEventDisplayMeta, KNOWN_EVENT_TYPES } from "../utils/eventDisplay";

interface EventChartProps {
  events: SafetyEvent[];
}

export default function EventChart({ events }: EventChartProps) {
  const knownEventTypeSet = new Set<string>(KNOWN_EVENT_TYPES);
  const unknownEventTypes = events
    .map((event) => event.event_type)
    .filter((type) => !knownEventTypeSet.has(type));
  const eventTypes = [
    ...KNOWN_EVENT_TYPES,
    ...Array.from(new Set(unknownEventTypes)),
  ] as EventType[];
  const counts = eventTypes.map((type) => {
    const meta = getEventDisplayMeta(type);

    return {
      type,
      label: meta.label,
      barClass: meta.barClass,
      count: events.filter((event) => event.event_type === type).length,
    };
  });
  const maxCount = Math.max(...counts.map((item) => item.count), 1);

  return (
    <section className="card panel">
      <div className="panel-header">
        <h2>이벤트 타입별 발생 수</h2>
        <span>유형별 현황</span>
      </div>
      <div className="bar-chart" aria-label="이벤트 유형별 발생 현황">
        {counts.map((item) => (
          <div className="bar-row" key={item.type}>
            <span className="bar-label">{item.label}</span>
            <div className="bar-track">
              <div
                className={`bar-fill ${item.barClass}`}
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
