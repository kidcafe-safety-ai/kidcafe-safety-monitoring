import { AlertTriangle, Clock3, ShieldAlert, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  getCurrentStatus,
  getDashboardSummary,
  getRecentEvents,
  RECENT_EVENT_LIMIT,
} from "../api/eventsApi";
import KpiCard from "../components/KpiCard";
import RecentEventList from "../components/RecentEventList";
import ZoneStatusPanel from "../components/ZoneStatusPanel";
import { usePolling } from "../hooks/usePolling";
import type { DashboardSummary, SafetyEvent, ZoneStatus } from "../types/event";
import type { CurrentStatus } from "../types/status";

const RECENT_EVENT_MINUTES = 10;

function getZonesFromCurrentStatus(currentStatus: CurrentStatus): ZoneStatus[] {
  return currentStatus.zone_occupancy.map((zone) => ({
    zone_id: zone.zone_id,
    zone_name: zone.zone_name,
    current_count: zone.current_count,
    risk_level: zone.risk_level,
  }));
}

export default function MonitoringPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [activeTrackCount, setActiveTrackCount] = useState<number | null>(null);
  const [recentEvents, setRecentEvents] = useState<SafetyEvent[]>([]);
  const [zones, setZones] = useState<ZoneStatus[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [apiErrors, setApiErrors] = useState({
    recentEvents: false,
    summary: false,
    zones: false,
  });

  const hasApiError = apiErrors.recentEvents || apiErrors.summary || apiErrors.zones;
  const dangerZoneOccupancy = zones
    .filter((zone) => zone.risk_level === "HIGH")
    .reduce((sum, zone) => sum + zone.current_count, 0);
  const dangerZoneOccupancyValue =
    apiErrors.zones && zones.length === 0 ? "-" : dangerZoneOccupancy;
  const recentEventCount = summary?.recent_event_count ?? "-";

  const loadDashboardData = useCallback(async () => {
    const [summaryData, eventData, currentStatusData] = await Promise.all([
      getDashboardSummary(),
      getRecentEvents(RECENT_EVENT_LIMIT, { minutes: RECENT_EVENT_MINUTES }),
      getCurrentStatus(),
    ]);

    setSummary(summaryData.data);
    setRecentEvents(eventData.data);
    if (currentStatusData.status !== "error") {
      setActiveTrackCount(currentStatusData.data.active_track_count);
      setZones(getZonesFromCurrentStatus(currentStatusData.data));
    }
    setApiErrors({
      recentEvents: eventData.status === "error",
      summary: summaryData.status === "error",
      zones: currentStatusData.status === "error",
    });
    setIsLoading(false);
  }, []);

  const loadRecentEvents = useCallback(async () => {
    const eventData = await getRecentEvents(RECENT_EVENT_LIMIT, {
      minutes: RECENT_EVENT_MINUTES,
    });
    setRecentEvents(eventData.data);
    setApiErrors((previous) => ({
      ...previous,
      recentEvents: eventData.status === "error",
    }));
  }, []);

  const loadSummary = useCallback(async () => {
    const summaryData = await getDashboardSummary();
    setSummary(summaryData.data);
    setApiErrors((previous) => ({
      ...previous,
      summary: summaryData.status === "error",
    }));
  }, []);

  const loadCurrentStatus = useCallback(async () => {
    const currentStatusData = await getCurrentStatus();
    if (currentStatusData.status !== "error") {
      setActiveTrackCount(currentStatusData.data.active_track_count);
      setZones(getZonesFromCurrentStatus(currentStatusData.data));
    }
    setApiErrors((previous) => ({
      ...previous,
      zones: currentStatusData.status === "error",
    }));
  }, []);

  useEffect(() => {
    loadDashboardData();
  }, [loadDashboardData]);

  usePolling(loadRecentEvents, 3000, !isLoading);
  usePolling(loadSummary, 10000, !isLoading);
  usePolling(loadCurrentStatus, 2000, !isLoading);

  return (
    <main className="page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>실시간 모니터링</h1>
            <span className="status-pill">Phase 2.5 Stable</span>
          </div>
          <p>Polling 기반 실시간 안전 대시보드</p>
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
          value={activeTrackCount ?? "-"}
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
          value={isLoading ? "-" : dangerZoneOccupancyValue}
        />
        <KpiCard
          icon={Clock3}
          status="최근 10분"
          title="최근 이벤트 수"
          value={isLoading ? "-" : recentEventCount}
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
