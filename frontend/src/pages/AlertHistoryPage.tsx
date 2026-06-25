import { useEffect, useMemo, useState } from "react";
import { getMockAlertHistory } from "../api/alertHistoryMockApi";
import type {
  AlertHistoryItem,
  AlertStatus,
} from "../types/alertHistory";
import type { EventType } from "../types/event";

type PeriodFilter = "전체" | "오늘" | "최근 7일";
type AlertStatusFilter = "전체" | AlertStatus;
type AlertTypeFilter = "전체" | EventType;

const PERIOD_FILTERS: PeriodFilter[] = ["전체", "오늘", "최근 7일"];
const STATUS_FILTERS: AlertStatusFilter[] = [
  "전체",
  "미확인",
  "확인중",
  "처리완료",
];
const TYPE_FILTERS: AlertTypeFilter[] = ["전체", "ENTER", "DWELL", "EXIT"];
const MOCK_TODAY = "2026-05-14";

function matchesPeriod(alert: AlertHistoryItem, period: PeriodFilter) {
  if (period === "전체") {
    return true;
  }

  const occurredDate = alert.occurred_at.slice(0, 10);

  if (period === "오늘") {
    return occurredDate === MOCK_TODAY;
  }

  const occurredTime = new Date(`${occurredDate}T00:00:00`).getTime();
  const todayTime = new Date(`${MOCK_TODAY}T00:00:00`).getTime();
  const diffDays = (todayTime - occurredTime) / (1000 * 60 * 60 * 24);

  return diffDays >= 0 && diffDays < 7;
}

function getSeverityLabel(severity: AlertHistoryItem["severity"]) {
  if (severity === "HIGH") {
    return "높음";
  }

  if (severity === "MEDIUM") {
    return "중간";
  }

  return "낮음";
}

function getStatusClass(status: AlertStatus) {
  if (status === "미확인") {
    return "risk-high";
  }

  if (status === "확인중") {
    return "risk-medium";
  }

  return "risk-normal";
}

export default function AlertHistoryPage() {
  const [alerts, setAlerts] = useState<AlertHistoryItem[]>([]);
  const [periodFilter, setPeriodFilter] = useState<PeriodFilter>("전체");
  const [zoneFilter, setZoneFilter] = useState("전체");
  const [statusFilter, setStatusFilter] = useState<AlertStatusFilter>("전체");
  const [typeFilter, setTypeFilter] = useState<AlertTypeFilter>("전체");
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);

  useEffect(() => {
    getMockAlertHistory().then((response) => {
      setAlerts(response.data);
      setSelectedAlertId(response.data[0]?.alert_id ?? null);
    });
  }, []);

  const zoneOptions = useMemo(
    () => ["전체", ...Array.from(new Set(alerts.map((alert) => alert.zone_name)))],
    [alerts],
  );

  const filteredAlerts = useMemo(
    () =>
      alerts.filter((alert) => {
        const matchesSelectedPeriod = matchesPeriod(alert, periodFilter);
        const matchesZone = zoneFilter === "전체" || alert.zone_name === zoneFilter;
        const matchesStatus =
          statusFilter === "전체" || alert.status === statusFilter;
        const matchesType =
          typeFilter === "전체" || alert.event_type === typeFilter;

        return matchesSelectedPeriod && matchesZone && matchesStatus && matchesType;
      }),
    [alerts, periodFilter, statusFilter, typeFilter, zoneFilter],
  );

  const selectedAlert =
    filteredAlerts.find((alert) => alert.alert_id === selectedAlertId) ??
    filteredAlerts[0] ??
    null;

  return (
    <main className="page alert-history-page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>알림 기록</h1>
            <span className="status-pill">Mock Prototype</span>
          </div>
          <p>위험 알림 발생 내역과 처리 상태를 확인하는 UI Preview 화면</p>
        </div>
      </div>

      <section className="card alert-filter-card">
        <label>
          <span>기간</span>
          <select
            value={periodFilter}
            onChange={(event) => setPeriodFilter(event.target.value as PeriodFilter)}
          >
            {PERIOD_FILTERS.map((period) => (
              <option key={period}>{period}</option>
            ))}
          </select>
        </label>
        <label>
          <span>구역</span>
          <select
            value={zoneFilter}
            onChange={(event) => setZoneFilter(event.target.value)}
          >
            {zoneOptions.map((zone) => (
              <option key={zone}>{zone}</option>
            ))}
          </select>
        </label>
        <label>
          <span>상태</span>
          <select
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as AlertStatusFilter)
            }
          >
            {STATUS_FILTERS.map((status) => (
              <option key={status}>{status}</option>
            ))}
          </select>
        </label>
        <label>
          <span>종류</span>
          <select
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value as AlertTypeFilter)}
          >
            {TYPE_FILTERS.map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
        </label>
      </section>

      {filteredAlerts.length === 0 ? (
        <div className="state-banner empty">표시할 알림 기록이 없습니다.</div>
      ) : null}

      <section className="alert-history-grid">
        <section className="card alert-table-card">
          <div className="panel-header">
            <div>
              <h2>알림 목록</h2>
              <span>mock prototype 데이터 기준</span>
            </div>
            <span>{filteredAlerts.length}건</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>발생 시간</th>
                  <th>알림 내용</th>
                  <th>위치</th>
                  <th>대상</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {filteredAlerts.map((alert) => (
                  <tr
                    className={
                      selectedAlert?.alert_id === alert.alert_id ? "selected-row" : ""
                    }
                    key={alert.alert_id}
                    onClick={() => setSelectedAlertId(alert.alert_id)}
                  >
                    <td>{alert.occurred_at}</td>
                    <td>
                      <span className={`type-badge type-${alert.event_type.toLowerCase()}`}>
                        {alert.event_type}
                      </span>
                      <strong className="alert-table-title">{alert.title}</strong>
                    </td>
                    <td>{alert.zone_name}</td>
                    <td>{alert.target}</td>
                    <td>
                      <span className={`risk-badge ${getStatusClass(alert.status)}`}>
                        {alert.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="alert-detail-stack">
          <section className="card alert-detail-card">
            <div className="panel-header">
              <div>
                <h2>알림 상세</h2>
                <span>선택된 알림의 상세 정보</span>
              </div>
            </div>

            {selectedAlert ? (
              <div className="alert-detail-content">
                <div>
                  <strong>{selectedAlert.title}</strong>
                  <p>{selectedAlert.message}</p>
                </div>
                <dl className="alert-detail-list">
                  <div>
                    <dt>구역명</dt>
                    <dd>{selectedAlert.zone_name}</dd>
                  </div>
                  <div>
                    <dt>대상</dt>
                    <dd>{selectedAlert.target}</dd>
                  </div>
                  <div>
                    <dt>심각도</dt>
                    <dd>
                      <span
                        className={`risk-badge risk-${selectedAlert.severity.toLowerCase()}`}
                      >
                        {getSeverityLabel(selectedAlert.severity)}
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt>처리 상태</dt>
                    <dd>
                      <span className={`risk-badge ${getStatusClass(selectedAlert.status)}`}>
                        {selectedAlert.status}
                      </span>
                    </dd>
                  </div>
                </dl>
              </div>
            ) : (
              <div className="state-banner empty">표시할 알림 기록이 없습니다.</div>
            )}
          </section>

          <section className="card alert-action-card">
            <div className="panel-header">
              <div>
                <h2>메모 / 조치</h2>
                <span>처리 메모 mock preview</span>
              </div>
            </div>
            <textarea
              readOnly
              value={selectedAlert?.action_note ?? "선택된 알림이 없습니다."}
            />
            <div className="alert-action-buttons">
              <button type="button">확인</button>
              <button type="button">처리 완료</button>
            </div>
          </section>
        </aside>
      </section>
    </main>
  );
}
