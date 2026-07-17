import { useCallback, useEffect, useMemo, useState } from "react";
import { getEvents } from "../api/eventsApi";
import { usePolling } from "../hooks/usePolling";
import type {
  AlertHistoryItem,
  AlertSeverity,
  AlertStatus,
} from "../types/alertHistory";
import type { EventType, SafetyEvent } from "../types/event";
import {
  formatEventCause,
  getEventDisplayMeta,
  KNOWN_EVENT_TYPES,
} from "../utils/eventDisplay";

type PeriodFilter = "전체" | "오늘" | "최근 7일";
type AlertStatusFilter = "전체" | AlertStatus;
type AlertTypeFilter = "전체" | EventType;
type SafetyEventWithApiFields = SafetyEvent & {
  created_at?: unknown;
  zone_name?: unknown;
};

const PERIOD_FILTERS: PeriodFilter[] = ["전체", "오늘", "최근 7일"];
const STATUS_FILTERS: AlertStatusFilter[] = [
  "전체",
  "미확인",
  "확인중",
  "처리완료",
];
const TYPE_FILTERS: AlertTypeFilter[] = ["전체", ...KNOWN_EVENT_TYPES];
const ALERT_POLLING_INTERVAL_MS = 5000;
const API_MODE = typeof import.meta.env.VITE_API_MODE === "string"
  ? import.meta.env.VITE_API_MODE.toLowerCase()
  : "mock";

function isApiMode() {
  return API_MODE === "api";
}

function readOptionalString(value: unknown) {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;
}

function formatDatePartsInSeoul(date: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const partMap = Object.fromEntries(parts.map((part) => [part.type, part.value]));

  return {
    dateKey: `${partMap.year}-${partMap.month}-${partMap.day}`,
    dateTime: `${partMap.year}-${partMap.month}-${partMap.day} ${partMap.hour}:${partMap.minute}:${partMap.second}`,
  };
}

function getSeoulDateKey(date = new Date()) {
  return formatDatePartsInSeoul(date).dateKey;
}

function formatOccurredAt(event: SafetyEventWithApiFields) {
  const createdAt = readOptionalString(event.created_at);

  if (createdAt) {
    const parsedDate = new Date(createdAt);

    if (!Number.isNaN(parsedDate.getTime())) {
      return formatDatePartsInSeoul(parsedDate).dateTime;
    }
  }

  return event.timestamp || "-";
}

function getDateKeyFromDisplayValue(value: string) {
  const dateKeyMatch = value.match(/^(\d{4}-\d{2}-\d{2})/);

  if (dateKeyMatch) {
    return dateKeyMatch[1];
  }

  const parsedDate = new Date(value);

  if (Number.isNaN(parsedDate.getTime())) {
    return null;
  }

  return getSeoulDateKey(parsedDate);
}

function getDateDiffDays(fromDateKey: string, toDateKey: string) {
  const fromTime = new Date(`${fromDateKey}T00:00:00+09:00`).getTime();
  const toTime = new Date(`${toDateKey}T00:00:00+09:00`).getTime();

  if (Number.isNaN(fromTime) || Number.isNaN(toTime)) {
    return null;
  }

  return (toTime - fromTime) / (1000 * 60 * 60 * 24);
}

function matchesPeriod(alert: AlertHistoryItem, period: PeriodFilter) {
  if (period === "전체") {
    return true;
  }

  const alertDateKey = getDateKeyFromDisplayValue(alert.occurred_at);

  if (alertDateKey === null) {
    return true;
  }

  const todayDateKey = getSeoulDateKey();

  if (period === "오늘") {
    return alertDateKey === todayDateKey;
  }

  const diffDays = getDateDiffDays(alertDateKey, todayDateKey);

  return diffDays !== null && diffDays >= 0 && diffDays < 7;
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

function getZoneName(event: SafetyEventWithApiFields) {
  const apiZoneName = readOptionalString(event.zone_name);

  if (apiZoneName) {
    return apiZoneName;
  }

  const zoneId = event.zone_id.trim();
  const normalizedZoneId = zoneId.toLowerCase();

  if (normalizedZoneId === "global" || normalizedZoneId === "__global__") {
    return "전체 구역";
  }

  return zoneId || "미지정 구역";
}

function getAlertMessage(event: SafetyEvent, causeText?: string) {
  if (event.event_type === "FALL_SUSPECT") {
    return `낙상 의심 이벤트가 발생했습니다. ${causeText ?? "원인 후보 없음"}`;
  }

  if (event.event_type === "ENTER_RESTRICTED") {
    return "제한구역 진입 이벤트가 발생했습니다.";
  }

  if (event.event_type === "DANGER_ZONE_DWELL") {
    return "위험구역 체류 이벤트가 발생했습니다.";
  }

  if (event.event_type === "ENTER") {
    return "구역 진입 이벤트가 발생했습니다.";
  }

  if (event.event_type === "DWELL") {
    return "구역 체류 이벤트가 발생했습니다.";
  }

  if (event.event_type === "EXIT") {
    return "구역 이탈 이벤트가 발생했습니다.";
  }

  return `${getEventDisplayMeta(event.event_type).label} 이벤트가 발생했습니다.`;
}

function mapEventToAlertHistoryItem(event: SafetyEvent): AlertHistoryItem {
  const eventWithApiFields = event as SafetyEventWithApiFields;
  const meta = getEventDisplayMeta(event.event_type);
  const zoneName = getZoneName(eventWithApiFields);
  const causeText =
    event.event_type === "FALL_SUSPECT"
      ? formatEventCause(event.cause)
      : undefined;
  const severity = (event.severity ?? meta.severity ?? "LOW") as AlertSeverity;

  return {
    alert_id: event.event_id,
    occurred_at: formatOccurredAt(eventWithApiFields),
    title: meta.label,
    zone_id: event.zone_id,
    zone_name: zoneName,
    target: `Track #${event.track_id}`,
    severity,
    status: "미확인",
    event_type: event.event_type,
    message: getAlertMessage(event, causeText),
    action_note: "조치 상태 저장은 Phase 4에서 연동 예정입니다.",
    cause_text: causeText,
  };
}

export default function AlertHistoryPage() {
  const [alerts, setAlerts] = useState<AlertHistoryItem[]>([]);
  const [periodFilter, setPeriodFilter] = useState<PeriodFilter>("전체");
  const [zoneFilter, setZoneFilter] = useState("전체");
  const [statusFilter, setStatusFilter] = useState<AlertStatusFilter>("전체");
  const [typeFilter, setTypeFilter] = useState<AlertTypeFilter>("전체");
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasApiError, setHasApiError] = useState(false);

  const loadAlerts = useCallback(async () => {
    const response = await getEvents();
    const mappedAlerts = response.data.map(mapEventToAlertHistoryItem);

    setAlerts(mappedAlerts);
    setHasApiError(response.status === "error");
    setIsLoading(false);
    setSelectedAlertId((currentAlertId) => {
      if (
        currentAlertId !== null &&
        mappedAlerts.some((alert) => alert.alert_id === currentAlertId)
      ) {
        return currentAlertId;
      }

      return mappedAlerts[0]?.alert_id ?? null;
    });
  }, []);

  usePolling(loadAlerts, ALERT_POLLING_INTERVAL_MS);

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

  useEffect(() => {
    if (
      selectedAlertId !== null &&
      filteredAlerts.some((alert) => alert.alert_id === selectedAlertId)
    ) {
      return;
    }

    setSelectedAlertId(filteredAlerts[0]?.alert_id ?? null);
  }, [filteredAlerts, selectedAlertId]);

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
            <span className="status-pill">
              {isApiMode() ? "실제 이벤트 연동" : "Mock 데이터 모드"}
            </span>
          </div>
          <p>
            {isApiMode()
              ? "FastAPI 이벤트 데이터를 기반으로 위험 알림 발생 내역을 표시합니다."
              : "Mock 이벤트 데이터를 기반으로 위험 알림 화면을 표시합니다."}
          </p>
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
              <option
                disabled={status === "확인중" || status === "처리완료"}
                key={status}
              >
                {status}
                {status === "확인중" || status === "처리완료"
                  ? " (Phase 4)"
                  : ""}
              </option>
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
              <option key={type} value={type}>
                {type === "전체" ? "전체" : getEventDisplayMeta(type).label}
              </option>
            ))}
          </select>
        </label>
      </section>

      {isLoading ? (
        <div className="state-banner">이벤트 데이터를 불러오는 중입니다.</div>
      ) : null}
      {hasApiError ? (
        <div className="state-banner error">
          API 연결에 실패했습니다. 이벤트 데이터를 불러올 수 없습니다.
        </div>
      ) : null}
      {!isApiMode() ? (
        <div className="state-banner alert-source-note">
          현재 VITE_API_MODE=mock 기준으로 표시 중입니다. API 모드에서는 FastAPI
          이벤트 데이터를 사용합니다.
        </div>
      ) : null}
      {!isLoading && filteredAlerts.length === 0 ? (
        <div className="state-banner empty">표시할 알림 기록이 없습니다.</div>
      ) : null}

      <section className="alert-history-grid">
        <section className="card alert-table-card">
          <div className="panel-header">
            <div>
              <h2>알림 목록</h2>
              <span>
                {isApiMode() ? "실제 이벤트 데이터 기준" : "mock 이벤트 데이터 기준"}
              </span>
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
                {filteredAlerts.map((alert) => {
                  const meta = getEventDisplayMeta(alert.event_type);

                  return (
                    <tr
                      className={
                        selectedAlert?.alert_id === alert.alert_id
                          ? "selected-row"
                          : ""
                      }
                      key={alert.alert_id}
                      onClick={() => setSelectedAlertId(alert.alert_id)}
                    >
                      <td>{alert.occurred_at}</td>
                      <td>
                        <span className={`type-badge ${meta.badgeClass}`}>
                          {meta.label}
                        </span>
                        <strong className="alert-table-title">{alert.title}</strong>
                        {alert.cause_text ? (
                          <span className="alert-cause-text">
                            {alert.cause_text}
                          </span>
                        ) : null}
                      </td>
                      <td>{alert.zone_name}</td>
                      <td>{alert.target}</td>
                      <td>
                        <span className={`risk-badge ${getStatusClass(alert.status)}`}>
                          {alert.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
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
                  {selectedAlert.cause_text ? (
                    <p className="alert-cause-text">{selectedAlert.cause_text}</p>
                  ) : null}
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
                <span>조치 상태 저장은 Phase 4에서 연동 예정</span>
              </div>
            </div>
            <textarea
              readOnly
              value={selectedAlert?.action_note ?? "선택된 알림이 없습니다."}
            />
            <p className="alert-disabled-action">
              확인 및 처리 완료 저장은 Phase 4에서 연동 예정입니다.
            </p>
            <div className="alert-action-buttons">
              <button
                disabled
                title="조치 상태 저장은 Phase 4에서 연동 예정입니다."
                type="button"
              >
                확인
              </button>
              <button
                disabled
                title="조치 상태 저장은 Phase 4에서 연동 예정입니다."
                type="button"
              >
                처리 완료
              </button>
            </div>
          </section>
        </aside>
      </section>
    </main>
  );
}
