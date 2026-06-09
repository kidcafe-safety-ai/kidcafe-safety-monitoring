import { AlertTriangle, Clock3, ShieldAlert, Users } from "lucide-react";
import { useCallback, useState } from "react";
import { getDashboardSummary, getRecentEvents, getZoneStatus } from "../api/eventsApi";
import KpiCard from "../components/KpiCard";
import RecentEventList from "../components/RecentEventList";
import ZoneStatusPanel from "../components/ZoneStatusPanel";
import { usePolling } from "../hooks/usePolling";
import type { DashboardSummary, SafetyEvent, ZoneStatus } from "../types/event";

export default function MonitoringPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [recentEvents, setRecentEvents] = useState<SafetyEvent[]>([]);
  const [zones, setZones] = useState<ZoneStatus[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasApiError, setHasApiError] = useState(false);

  const loadDashboardData = useCallback(async () => {
    const [summaryData, eventData, zoneData] = await Promise.all([
      getDashboardSummary(),
      getRecentEvents(5),
      getZoneStatus(),
    ]);

    setSummary(summaryData.data);
    setRecentEvents(eventData.data);
    setZones(zoneData.data);
    setHasApiError(
      [summaryData, eventData, zoneData].some((response) => response.status === "error"),
    );
    setIsLoading(false);
  }, []);

  const loadRecentEvents = useCallback(async () => {
    const eventData = await getRecentEvents(5);
    setRecentEvents(eventData.data);
    setHasApiError((previous) => previous || eventData.status === "error");
  }, []);

  const loadSummary = useCallback(async () => {
    const summaryData = await getDashboardSummary();
    setSummary(summaryData.data);
    setHasApiError((previous) => previous || summaryData.status === "error");
  }, []);

  const loadZones = useCallback(async () => {
    const zoneData = await getZoneStatus();
    setZones(zoneData.data);
    setHasApiError((previous) => previous || zoneData.status === "error");
  }, []);

  usePolling(loadDashboardData, 5000);
  usePolling(loadRecentEvents, 3000, !isLoading);
  usePolling(loadSummary, 5000, !isLoading);
  usePolling(loadZones, 2000, !isLoading);

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

      {isLoading ? <div className="state-banner">데이터를 불러오는 중입니다.</div> : null}
      {hasApiError ? (
        <div className="state-banner error">
          API 연결에 실패했습니다. mock 또는 기본값으로 화면을 표시합니다.
        </div>
      ) : null}

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
          {!isLoading && recentEvents.length === 0 ? (
            <div className="state-banner empty">표시할 이벤트가 없습니다.</div>
          ) : null}
          <RecentEventList events={recentEvents} />
          <ZoneStatusPanel zones={zones} />
        </aside>
      </section>
    </main>
  );
}
