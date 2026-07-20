import type { SafetyEvent } from "../types/event";
import { formatEventCause, getEventDisplayMeta } from "../utils/eventDisplay";

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
                <th>영상 소스</th>
                <th>위험도</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const meta = getEventDisplayMeta(event.event_type);
                const shouldShowTechnicalType = meta.label !== event.event_type;
                const causeText =
                  event.event_type === "FALL_SUSPECT"
                    ? formatEventCause(event.cause)
                    : "-";

                return (
                  <tr key={event.event_id}>
                    <td>{formatTime(event.timestamp)}</td>
                    <td>
                      <span className={`type-badge ${meta.badgeClass}`}>
                        {meta.label}
                      </span>
                      {shouldShowTechnicalType ? (
                        <span className="event-raw-type">{event.event_type}</span>
                      ) : null}
                    </td>
                    <td>{event.track_id}</td>
                    <td>{event.zone_id}</td>
                    <td>{causeText}</td>
                    <td>{event.frame_number}</td>
                    <td>{event.video_source}</td>
                    <td>{meta.severity ?? event.severity ?? "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-empty-state">표시할 이벤트가 없습니다.</div>
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
