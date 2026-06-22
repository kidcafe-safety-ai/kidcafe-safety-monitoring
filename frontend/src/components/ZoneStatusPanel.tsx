import type { ZoneStatus } from "../types/event";

interface ZoneStatusPanelProps {
  zones: ZoneStatus[];
}

export default function ZoneStatusPanel({ zones }: ZoneStatusPanelProps) {
  return (
    <section className="card panel">
      <div className="panel-header">
        <h2>위험구역 상태</h2>
        <span>{zones.length}개 구역</span>
      </div>
      <div className="zone-list">
        {zones.map((zone) => (
          <article className="zone-item" key={zone.zone_id}>
            <div>
              <strong>{zone.zone_name}</strong>
              <p>{zone.zone_id}</p>
            </div>
            <div className="zone-count">
              <strong>{zone.current_count}</strong>
              <span className={`risk-badge risk-${zone.risk_level?.toLowerCase()}`}>
                {zone.risk_level ?? "NORMAL"}
              </span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
