import { AlertTriangle, Clock3, ShieldAlert, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { getRecentEvents, getSummary, getZoneStatus } from "../api/eventsApi";
import KpiCard from "../components/KpiCard";
import RecentEventList from "../components/RecentEventList";
import ZoneStatusPanel from "../components/ZoneStatusPanel";
import type { DashboardSummary, SafetyEvent, ZoneStatus } from "../types/event";

export default function MonitoringPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [recentEvents, setRecentEvents] = useState<SafetyEvent[]>([]);
  const [zones, setZones] = useState<ZoneStatus[]>([]);

  useEffect(() => {
    async function loadDashboardData() {
      const [summaryData, eventData, zoneData] = await Promise.all([
        getSummary(),
        getRecentEvents(),
        getZoneStatus(),
      ]);
      setSummary(summaryData.data);
      setRecentEvents(eventData.data);
      setZones(zoneData.data);
    }

    loadDashboardData();
  }, []);

  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>실시간 모니터링</h1>
            <span className="status-pill">Phase 1.5 Mock</span>
          </div>
          <p>Mock 이벤트 기반 Phase 1.5 운영 대시보드</p>
        </div>
      </div>

      <section className="kpi-grid">
        <KpiCard
          icon={Users}
          status="실시간 기준"
          title="현재 감지 인원"
          value={summary?.active_tracks ?? "-"}
        />
        <KpiCard
          icon={AlertTriangle}
          status="금일 누적"
          title="오늘 발생 이벤트 수"
          value={summary?.today_event_count ?? "-"}
        />
        <KpiCard
          icon={ShieldAlert}
          status="주의 필요"
          title="위험구역 체류 인원"
          value={summary?.danger_zone_occupancy ?? "-"}
        />
        <KpiCard
          icon={Clock3}
          status="최근 10분"
          title="최근 이벤트 수"
          value={summary?.recent_event_count ?? "-"}
        />
      </section>

      <section className="monitoring-grid">
        <div className="video-placeholder">
          <span>Live Video 예정</span>
        </div>
        <aside className="side-stack">
          <RecentEventList events={recentEvents} />
          <ZoneStatusPanel zones={zones} />
        </aside>
      </section>
    </main>
  );
}
