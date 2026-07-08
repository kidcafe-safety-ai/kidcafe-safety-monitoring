import { useEffect, useMemo, useState } from "react";
import { getMockReports } from "../api/reportMockApi";
import type { ReportType, SafetyReport } from "../types/report";

type ReportTypeFilter = "전체" | ReportType;

const REPORT_TYPE_OPTIONS: ReportTypeFilter[] = [
  "전체",
  "오늘 리포트",
  "주간 리포트",
  "구역 리포트",
];

function formatPeriod(report: SafetyReport) {
  return `${report.period_start} - ${report.period_end}`;
}

function getTopZoneSummary(report: SafetyReport) {
  return report.top_zones.map((zone) => zone.zone_name).join(", ");
}

export default function ReportPage() {
  const [reports, setReports] = useState<SafetyReport[]>([]);
  const [groupFilter, setGroupFilter] = useState("전체");
  const [periodFilter, setPeriodFilter] = useState("전체");
  const [typeFilter, setTypeFilter] = useState<ReportTypeFilter>("전체");
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);

  useEffect(() => {
    getMockReports().then((response) => {
      setReports(response.data);
      setSelectedReportId(response.data[0]?.report_id ?? null);
    });
  }, []);

  const groupOptions = useMemo(
    () => ["전체", ...Array.from(new Set(reports.map((report) => report.child_group)))],
    [reports],
  );

  const periodOptions = useMemo(
    () => [
      "전체",
      ...Array.from(
        new Set(
          reports.map((report) => `${report.period_start} - ${report.period_end}`),
        ),
      ),
    ],
    [reports],
  );

  const filteredReports = useMemo(
    () =>
      reports.filter((report) => {
        const matchesGroup =
          groupFilter === "전체" || report.child_group === groupFilter;
        const matchesPeriod =
          periodFilter === "전체" || formatPeriod(report) === periodFilter;
        const matchesType =
          typeFilter === "전체" || report.report_type === typeFilter;

        return matchesGroup && matchesPeriod && matchesType;
      }),
    [groupFilter, periodFilter, reports, typeFilter],
  );

  const selectedReport =
    filteredReports.find((report) => report.report_id === selectedReportId) ??
    filteredReports[0] ??
    null;

  return (
    <main className="page report-page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>리포트 생성</h1>
            <span className="status-pill">Mock Prototype</span>
          </div>
          <p>운영 기록을 보호자 공유용 리포트로 미리 구성하는 UI Preview 화면</p>
        </div>
      </div>

      <section className="report-layout">
        <aside className="report-control-stack">
          <section className="card report-selector-card">
            <div className="panel-header">
              <div>
                <h2>대상 선택</h2>
                <span>리포트 조건 mock 설정</span>
              </div>
            </div>
            <div className="report-form">
              <label>
                <span>대상 그룹</span>
                <select
                  value={groupFilter}
                  onChange={(event) => setGroupFilter(event.target.value)}
                >
                  {groupOptions.map((group) => (
                    <option key={group}>{group}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>기간 선택</span>
                <input
                  list="report-period-options"
                  value={periodFilter}
                  onChange={(event) => setPeriodFilter(event.target.value)}
                />
                <datalist id="report-period-options">
                  {periodOptions.map((period) => (
                    <option key={period} value={period} />
                  ))}
                </datalist>
              </label>
              <label>
                <span>리포트 유형</span>
                <select
                  value={typeFilter}
                  onChange={(event) =>
                    setTypeFilter(event.target.value as ReportTypeFilter)
                  }
                >
                  {REPORT_TYPE_OPTIONS.map((type) => (
                    <option key={type}>{type}</option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section className="card report-kpi-card">
            <div className="panel-header">
              <div>
                <h2>리포트 요약</h2>
                <span>선택 리포트 기준</span>
              </div>
            </div>
            {selectedReport ? (
              <div className="report-summary-panel">
                <div className="report-kpi-grid">
                  <div>
                    <span>전체 알림 수</span>
                    <strong>{selectedReport.total_events}</strong>
                  </div>
                  <div>
                    <span>위험 알림 수</span>
                    <strong>{selectedReport.high_risk_events}</strong>
                  </div>
                  <div>
                    <span>장기 체류 알림 수</span>
                    <strong>{selectedReport.dwell_events}</strong>
                  </div>
                  <div>
                    <span>주요 발생 구역</span>
                    <strong>{selectedReport.top_zones[0]?.zone_name ?? "-"}</strong>
                  </div>
                </div>
              </div>
            ) : (
              <div className="state-banner empty">표시할 리포트가 없습니다.</div>
            )}
          </section>

        </aside>

        <section className="card report-preview-card">
          <div className="panel-header">
            <div>
              <h2>오늘의 놀이 리포트 미리보기</h2>
              <span>보호자 공유 화면 preview</span>
            </div>
            <span>{selectedReport?.report_date ?? "-"}</span>
          </div>

          {selectedReport ? (
            <div className="report-preview">
              <div className="report-preview-heading">
                <strong>{selectedReport.summary_title}</strong>
                <span>{selectedReport.child_group}</span>
              </div>
              <dl className="report-preview-list">
                <div>
                  <dt>리포트 날짜</dt>
                  <dd>{selectedReport.report_date}</dd>
                </div>
                <div>
                  <dt>주요 활동 구역</dt>
                  <dd>{getTopZoneSummary(selectedReport)}</dd>
                </div>
                <div>
                  <dt>이용 시간</dt>
                  <dd>{formatPeriod(selectedReport)}</dd>
                </div>
                <div>
                  <dt>안전 알림 요약</dt>
                  <dd>
                    총 {selectedReport.total_events}건 중 위험 알림{" "}
                    {selectedReport.high_risk_events}건, 장기 체류 알림{" "}
                    {selectedReport.dwell_events}건
                  </dd>
                </div>
              </dl>
              <div className="report-note">
                <span>보호자에게 보여줄 안전 메모</span>
                <p>{selectedReport.safety_note}</p>
              </div>
              <div className="report-note">
                <span>권장 조치</span>
                <p>{selectedReport.recommended_action}</p>
              </div>
            </div>
          ) : (
            <div className="state-banner empty">표시할 리포트가 없습니다.</div>
          )}
          <div className="report-preview-actions">
            <div>
              <strong>리포트 생성</strong>
              <span>파일 생성 기능 없는 UI preview</span>
            </div>
            <div className="report-action-buttons">
              <button type="button">PDF 다운로드</button>
            </div>
          </div>
        </section>
      </section>

      {filteredReports.length === 0 ? (
        <div className="state-banner empty">표시할 리포트가 없습니다.</div>
      ) : null}

      <section className="card report-list-card">
        <div className="panel-header">
          <div>
            <h2>리포트 목록</h2>
            <span>mock prototype 데이터 기준</span>
          </div>
          <span>{filteredReports.length}건</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>생성일</th>
                <th>대상</th>
                <th>기간</th>
                <th>주요 상태</th>
                <th>공유 대상</th>
              </tr>
            </thead>
            <tbody>
              {filteredReports.map((report) => (
                <tr
                  className={
                    selectedReport?.report_id === report.report_id ? "selected-row" : ""
                  }
                  key={report.report_id}
                  onClick={() => setSelectedReportId(report.report_id)}
                >
                  <td>{report.generated_at}</td>
                  <td>{report.child_group}</td>
                  <td>{formatPeriod(report)}</td>
                  <td>
                    {report.report_type} / 위험 {report.high_risk_events}건
                  </td>
                  <td>{report.share_target}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
