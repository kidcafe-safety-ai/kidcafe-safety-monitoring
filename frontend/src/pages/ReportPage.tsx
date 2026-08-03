import { useEffect, useMemo, useRef, useState } from "react";
import { getEventsPage, isEventsApiMode } from "../api/eventsApi";
import type { SafetyEvent } from "../types/event";
import {
  buildSeoulInclusiveDateRange,
  formatSeoulDateTimeDisplay,
  getSeoulDateKey,
  parseUtcTimestamp,
  type SeoulInclusiveDateRange,
} from "../utils/eventDateTime";
import {
  formatEventCause,
  formatEventZone,
  formatTrackId,
  getEventDisplayMeta,
  getEventSeverity,
  getSeverityDisplay,
} from "../utils/eventDisplay";
import { aggregateReportEvents } from "../utils/reportAggregation";

type ReportState = "idle" | "loading" | "success" | "empty" | "error";

const REPORT_PAGE_SIZE = 100;
const MAX_REPORT_DAYS = 31;
const MAX_REPORT_PAGES = 200;
const EVENT_PREVIEW_LIMIT = 20;

interface LoadedReportEvents {
  events: SafetyEvent[];
  total: number;
  pagesLoaded: number;
}

function getReportErrorMessage(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "요청이 취소되었습니다.";
  }

  return error instanceof Error && error.message.length > 0
    ? error.message
    : "리포트 데이터를 불러올 수 없습니다.";
}

function formatCreatedAt(event: SafetyEvent) {
  const createdAtDate = parseUtcTimestamp(event.created_at);

  return createdAtDate === null ? "-" : formatSeoulDateTimeDisplay(createdAtDate);
}

function formatReportRange(range: SeoulInclusiveDateRange | null) {
  if (range === null) {
    return "-";
  }

  return `${range.startDateKey} ~ ${range.endDateKey}`;
}

async function loadAllEventsForReport(
  range: SeoulInclusiveDateRange,
  signal: AbortSignal,
): Promise<LoadedReportEvents> {
  const accumulatedEvents: SafetyEvent[] = [];
  const seenEventIds = new Set<string>();
  const requestedOffsets = new Set<number>();
  let offset = 0;
  let referenceTotal: number | null = null;
  let pagesLoaded = 0;
  let completed = false;

  while (pagesLoaded < MAX_REPORT_PAGES) {
    if (signal.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }

    if (requestedOffsets.has(offset)) {
      throw new Error("이벤트 pagination offset이 반복되어 조회를 중단했습니다.");
    }

    requestedOffsets.add(offset);

    const response = await getEventsPage(
      {
        limit: REPORT_PAGE_SIZE,
        offset,
        created_from: range.createdFrom,
        created_to: range.createdTo,
      },
      { signal },
    );

    if (signal.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }

    if (response.status === "error") {
      throw new Error(response.message ?? "이벤트 목록 조회에 실패했습니다.");
    }

    const page = response.data;
    const pageItems = page.items;
    const pageCount = Math.max(page.count, pageItems.length);
    const pageLimit = Math.max(1, page.limit || REPORT_PAGE_SIZE);
    let pageReferenceTotal: number;

    if (referenceTotal === null) {
      pageReferenceTotal = Math.max(0, page.total);
      referenceTotal = pageReferenceTotal;
    } else {
      pageReferenceTotal = referenceTotal;
    }
    pagesLoaded += 1;

    pageItems.forEach((event) => {
      if (seenEventIds.has(event.event_id)) {
        return;
      }

      seenEventIds.add(event.event_id);
      accumulatedEvents.push(event);
    });

    if (pageReferenceTotal === 0 || offset + pageCount >= pageReferenceTotal) {
      completed = true;
      break;
    }

    if (pageCount === 0) {
      throw new Error("이벤트 pagination 응답이 비정상입니다.");
    }

    offset += pageLimit;
  }

  if (!completed && pagesLoaded >= MAX_REPORT_PAGES) {
    throw new Error("이벤트 page 수가 너무 많아 조회를 중단했습니다.");
  }

  const expectedTotal = referenceTotal ?? 0;

  if (completed && accumulatedEvents.length !== expectedTotal) {
    throw new Error(
      "조회 중 이벤트 목록이 변경되어 리포트를 완성할 수 없습니다. 다시 조회해 주세요.",
    );
  }

  return {
    events: accumulatedEvents,
    total: expectedTotal,
    pagesLoaded,
  };
}

export default function ReportPage() {
  const defaultDateKey = getSeoulDateKey();
  const [startDate, setStartDate] = useState(defaultDateKey);
  const [endDate, setEndDate] = useState(defaultDateKey);
  const [reportState, setReportState] = useState<ReportState>("idle");
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [activeRange, setActiveRange] = useState<SeoulInclusiveDateRange | null>(
    null,
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pagesLoaded, setPagesLoaded] = useState(0);
  const [reportedTotal, setReportedTotal] = useState(0);
  const requestIdRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  const reportSummary = useMemo(() => aggregateReportEvents(events), [events]);
  const previewEvents = events.slice(0, EVENT_PREVIEW_LIMIT);

  useEffect(
    () => () => {
      abortControllerRef.current?.abort();
    },
    [],
  );

  const handleLoadReport = async () => {
    const { range, errorMessage: dateErrorMessage } =
      buildSeoulInclusiveDateRange(startDate, endDate);

    if (range === null) {
      setReportState("error");
      setErrorMessage(dateErrorMessage);
      return;
    }

    if (range.inclusiveDays > MAX_REPORT_DAYS) {
      setReportState("error");
      setErrorMessage(`리포트 조회 기간은 최대 ${MAX_REPORT_DAYS}일까지 가능합니다.`);
      return;
    }

    abortControllerRef.current?.abort();

    const requestId = requestIdRef.current + 1;
    const abortController = new AbortController();
    requestIdRef.current = requestId;
    abortControllerRef.current = abortController;

    setReportState("loading");
    setErrorMessage(null);
    setEvents([]);
    setActiveRange(range);
    setPagesLoaded(0);
    setReportedTotal(0);

    try {
      const result = await loadAllEventsForReport(
        range,
        abortController.signal,
      );

      if (requestIdRef.current !== requestId || abortController.signal.aborted) {
        return;
      }

      setEvents(result.events);
      setPagesLoaded(result.pagesLoaded);
      setReportedTotal(result.total);
      setReportState(result.total === 0 || result.events.length === 0 ? "empty" : "success");
    } catch (error) {
      if (requestIdRef.current !== requestId || abortController.signal.aborted) {
        return;
      }

      setEvents([]);
      setPagesLoaded(0);
      setReportedTotal(0);
      setReportState("error");
      setErrorMessage(getReportErrorMessage(error));
    }
  };

  const renderReportBody = () => {
    if (reportState === "idle") {
      return (
        <div className="state-banner empty">
          조회할 날짜 범위를 선택한 뒤 리포트 조회를 눌러주세요.
        </div>
      );
    }

    if (reportState === "loading") {
      return (
        <div className="state-banner">
          선택 기간의 안전 이벤트 전체를 불러오는 중입니다.
        </div>
      );
    }

    if (reportState === "error") {
      return (
        <div className="state-banner error">
          {errorMessage ?? "리포트 데이터를 불러올 수 없습니다."}
        </div>
      );
    }

    if (reportState === "empty") {
      return (
        <div className="state-banner empty">
          선택한 기간에 안전 이벤트가 없습니다.
        </div>
      );
    }

    return (
      <div className="report-preview">
        <div className="report-preview-heading">
          <strong>기간별 안전 이벤트 리포트</strong>
          <span>{formatReportRange(activeRange)}</span>
        </div>
        <dl className="report-preview-list">
          <div>
            <dt>조회 기준</dt>
            <dd>Event created_at 기준, Asia/Seoul 날짜 범위</dd>
          </div>
          <div>
            <dt>API 요청 범위</dt>
            <dd>
              {activeRange?.createdFrom ?? "-"} 이상, {activeRange?.createdTo ?? "-"} 미만
            </dd>
          </div>
          <div>
            <dt>전체 이벤트</dt>
            <dd>{reportSummary.totalEvents}건</dd>
          </div>
          <div>
            <dt>HIGH 이벤트</dt>
            <dd>{reportSummary.highSeverityCount}건</dd>
          </div>
          <div>
            <dt>낙상 의심</dt>
            <dd>{reportSummary.fallSuspectCount}건</dd>
          </div>
          <div>
            <dt>위험 Zone 관련</dt>
            <dd>{reportSummary.dangerZoneEventCount}건</dd>
          </div>
          <div>
            <dt>Pagination</dt>
            <dd>
              {pagesLoaded} page 조회 · total {reportedTotal}건 · 중복 event_id 제외
            </dd>
          </div>
        </dl>
      </div>
    );
  };

  return (
    <main className="page report-page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>리포트 생성</h1>
            <span className="status-pill">
              {isEventsApiMode() ? "실제 이벤트 연동" : "Mock 데이터 모드"}
            </span>
          </div>
          <p>GET /events 기간 조회 결과를 기반으로 읽기 전용 안전 리포트를 집계합니다.</p>
        </div>
      </div>

      <section className="report-layout">
        <aside className="report-control-stack">
          <section className="card report-selector-card">
            <div className="panel-header">
              <div>
                <h2>기간 선택</h2>
                <span>서울 날짜 기준으로 created_at 범위를 조회합니다.</span>
              </div>
            </div>
            <div className="report-form">
              <label>
                <span>시작일</span>
                <input
                  disabled={reportState === "loading"}
                  onChange={(event) => setStartDate(event.target.value)}
                  type="date"
                  value={startDate}
                />
              </label>
              <label>
                <span>종료일</span>
                <input
                  disabled={reportState === "loading"}
                  onChange={(event) => setEndDate(event.target.value)}
                  type="date"
                  value={endDate}
                />
              </label>
              <button
                className="report-submit-button"
                disabled={reportState === "loading"}
                onClick={handleLoadReport}
                type="button"
              >
                {reportState === "loading" ? "조회 중..." : "리포트 조회"}
              </button>
            </div>
          </section>

          <section className="card report-kpi-card">
            <div className="panel-header">
              <div>
                <h2>리포트 요약</h2>
                <span>선택 기간 전체 이벤트 기준</span>
              </div>
            </div>
            <div className="report-summary-panel">
              <div className="report-kpi-grid">
                <div>
                  <span>전체 이벤트</span>
                  <strong>{reportSummary.totalEvents}</strong>
                </div>
                <div>
                  <span>낙상 의심</span>
                  <strong>{reportSummary.fallSuspectCount}</strong>
                </div>
                <div>
                  <span>HIGH 이벤트</span>
                  <strong>{reportSummary.highSeverityCount}</strong>
                </div>
                <div>
                  <span>위험 Zone 관련</span>
                  <strong>{reportSummary.dangerZoneEventCount}</strong>
                </div>
              </div>
            </div>
          </section>
        </aside>

        <section className="card report-preview-card">
          <div className="panel-header">
            <div>
              <h2>기간별 안전 이벤트 리포트</h2>
              <span>저장·공유 없이 Frontend에서 읽기 전용으로 집계합니다.</span>
            </div>
            <span>{formatReportRange(activeRange)}</span>
          </div>
          {renderReportBody()}
        </section>
      </section>

      {reportState === "success" ? (
        <>
          <section className="card report-list-card">
            <div className="panel-header">
              <div>
                <h2>EventType별 발생 수</h2>
                <span>공통 이벤트 표시 메타데이터 기준</span>
              </div>
              <span>{reportSummary.eventTypeCounts.length}종</span>
            </div>
            <div className="report-breakdown-grid">
              {reportSummary.eventTypeCounts.map((item) => {
                const meta = getEventDisplayMeta(item.eventType);

                return (
                  <div className="report-breakdown-item" key={item.eventType}>
                    <span className={`type-badge ${meta.badgeClass}`}>
                      {item.label}
                    </span>
                    <strong>{item.count}건</strong>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="card report-list-card">
            <div className="panel-header">
              <div>
                <h2>Zone별 발생 수</h2>
                <span>Event에 포함된 zone_name 또는 zone_id 기준</span>
              </div>
              <span>{reportSummary.zoneCounts.length}개 Zone</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Zone</th>
                    <th>발생 수</th>
                  </tr>
                </thead>
                <tbody>
                  {reportSummary.zoneCounts.map((zone) => (
                    <tr key={zone.zoneKey}>
                      <td className="text-wrap">{zone.label}</td>
                      <td>{zone.count}건</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card report-list-card">
            <div className="panel-header">
              <div>
                <h2>조회된 안전 이벤트</h2>
                <span>created_at 최신순, 최대 {EVENT_PREVIEW_LIMIT}건 미리보기</span>
              </div>
              <span>{events.length}건</span>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>발생 시각</th>
                    <th>이벤트</th>
                    <th>위험도</th>
                    <th>Track</th>
                    <th>Zone</th>
                    <th>원인 후보</th>
                  </tr>
                </thead>
                <tbody>
                  {previewEvents.map((event) => {
                    const meta = getEventDisplayMeta(event.event_type);
                    const severity = getEventSeverity(event.event_type, event.severity);
                    const severityDisplay = getSeverityDisplay(severity);
                    const causeText =
                      event.event_type === "FALL_SUSPECT"
                        ? formatEventCause(event.cause)
                        : "-";

                    return (
                      <tr key={event.event_id}>
                        <td>{formatCreatedAt(event)}</td>
                        <td>
                          <span className={`type-badge ${meta.badgeClass}`}>
                            {meta.label}
                          </span>
                        </td>
                        <td>
                          <span className={`risk-badge ${severityDisplay.className}`}>
                            {severityDisplay.iconLabel} · {severityDisplay.label}
                          </span>
                        </td>
                        <td>{formatTrackId(event.track_id)}</td>
                        <td className="text-wrap">{formatEventZone(event)}</td>
                        <td className="text-wrap">{causeText}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
