import type { SafetyEvent } from "../types/event";
import {
  formatEventCause,
  formatEventSource,
  formatEventZone,
  getEventDisplayMeta,
  getEventSeverity,
  getSeverityDisplay,
} from "../utils/eventDisplay";

interface EventTableProps {
  events: SafetyEvent[];
  totalCount?: number;
  pagination?: {
    currentPage: number;
    totalPages: number;
    onPrevious: () => void;
    onNext: () => void;
  };
}

function formatTime(timestamp: string) {
  return timestamp;
}

export default function EventTable({
  events,
  totalCount = events.length,
  pagination,
}: EventTableProps) {
  const hasEvents = totalCount > 0;
  const shouldShowPagination = pagination !== undefined && pagination.totalPages > 0;

  return (
    <section className="card table-card">
      <div className="panel-header">
        <h2>이벤트 테이블</h2>
        <span>{totalCount}건</span>
      </div>
      {hasEvents ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>시간</th>
                <th>이벤트</th>
                <th>추적 ID</th>
                <th>구역</th>
                <th>원인 후보</th>
                <th>프레임</th>
                <th>입력 출처</th>
                <th>위험도</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const meta = getEventDisplayMeta(event.event_type);
                const causeText =
                  event.event_type === "FALL_SUSPECT"
                    ? formatEventCause(event.cause)
                    : "-";
                const severityDisplay = getSeverityDisplay(
                  getEventSeverity(event.event_type, event.severity),
                );

                return (
                  <tr key={event.event_id}>
                    <td>{formatTime(event.timestamp)}</td>
                    <td>
                      <span className={`type-badge ${meta.badgeClass}`}>
                        {meta.label}
                      </span>
                    </td>
                    <td>{event.track_id}</td>
                    <td>{formatEventZone(event)}</td>
                    <td>{causeText}</td>
                    <td>{event.frame_number}</td>
                    <td>{formatEventSource(event.video_source)}</td>
                    <td>{severityDisplay.label}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-empty-state">현재 감지된 안전 이벤트가 없습니다.</div>
      )}
      {shouldShowPagination ? (
        <div className="table-pagination">
          <button
            disabled={pagination.currentPage <= 1}
            onClick={pagination.onPrevious}
            type="button"
          >
            이전
          </button>
          <span>
            {pagination.currentPage} / {pagination.totalPages}
          </span>
          <button
            disabled={pagination.currentPage >= pagination.totalPages}
            onClick={pagination.onNext}
            type="button"
          >
            다음
          </button>
        </div>
      ) : null}
    </section>
  );
}
