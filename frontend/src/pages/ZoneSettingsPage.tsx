import { useEffect, useMemo, useState } from "react";
import { getMockZoneSettings } from "../api/zoneSettingsMockApi";
import type { AlertZoneSetting } from "../types/zoneSettings";

function getZoneClass(zoneType: AlertZoneSetting["zone_type"]) {
  if (zoneType === "위험구역") {
    return "zone-danger";
  }

  if (zoneType === "주의구역") {
    return "zone-warning";
  }

  return "zone-watch";
}

function formatPoints(points: [number, number][]) {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

const COORDINATE_BASIS = "영상 프레임";

export default function ZoneSettingsPage() {
  const [zones, setZones] = useState<AlertZoneSetting[]>([]);

  useEffect(() => {
    getMockZoneSettings().then((response) => {
      setZones(response.data);
    });
  }, []);

  const selectedZone = zones[0];

  const tableRows = useMemo(
    () =>
      zones.map((zone, index) => ({
        ...zone,
        number: index + 1,
      })),
    [zones],
  );

  return (
    <section className="page zone-settings-page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>안전구역 / 알림 설정</h1>
            <span className="status-pill">Mock Prototype</span>
          </div>
          <p>위험구역 기준과 알림 조건을 미리 구성하는 UI Preview 화면</p>
        </div>
      </div>

      <div className="zone-settings-grid">
        <section className="card zone-preview-card">
          <div className="panel-header">
            <div>
              <h2>영상 프레임 미리보기</h2>
              <span>테스트 영상 기준 위험구역 polygon 표시</span>
            </div>
            <span className="status-pill">Video Frame Mock</span>
          </div>
          <div className="zone-map">
            <div className="video-frame-preview">
              <div className="video-hud top-left">
                <strong>CAM 01</strong>
                <span>TEST VIDEO</span>
              </div>
              <div className="video-hud top-right">
                <strong>Frame #1230</strong>
                <span>Mock Preview</span>
              </div>
              <div className="video-guide horizontal" />
              <div className="video-guide vertical" />
              <div className="video-subject subject-one" />
              <div className="video-subject subject-two" />
              <svg
                aria-label="영상 프레임 위험구역 mock polygon"
                className="zone-overlay"
                viewBox="0 0 100 100"
              >
                {zones.map((zone) => (
                  <g className={getZoneClass(zone.zone_type)} key={zone.zone_id}>
                    <polygon points={formatPoints(zone.points)} />
                    {zone.points.map(([x, y]) => (
                      <circle cx={x} cy={y} key={`${x}-${y}`} r="1.5" />
                    ))}
                    <text x={zone.points[0][0] + 2} y={zone.points[0][1] + 8}>
                      {zone.zone_name}
                    </text>
                  </g>
                ))}
              </svg>
            </div>
          </div>
        </section>

        <section className="card zone-config-card">
          <div className="panel-header">
            <div>
              <h2>선택 구역 설정</h2>
              <span>영상 프레임 기준 mock 설정 카드</span>
            </div>
          </div>

          {selectedZone ? (
            <div className="zone-form-preview">
              <label>
                <span>구역 이름</span>
                <input readOnly value={selectedZone.zone_name} />
              </label>
              <label>
                <span>구역 유형</span>
                <select value={selectedZone.zone_type} disabled>
                  <option>위험구역</option>
                  <option>주의구역</option>
                  <option>관찰구역</option>
                </select>
              </label>
              <label>
                <span>체류 경고 시간</span>
                <input readOnly value={`${selectedZone.dwell_threshold_sec}초`} />
              </label>
              <div className="setting-row">
                <span>알림 사용 여부</span>
                <span
                  className={
                    selectedZone.alert_enabled ? "toggle-preview on" : "toggle-preview"
                  }
                >
                  <span />
                </span>
              </div>
              <div className="setting-row">
                <span>좌표 기준</span>
                <strong>{COORDINATE_BASIS}</strong>
              </div>
            </div>
          ) : null}
        </section>
      </div>

      <section className="card zone-table-card">
        <div className="panel-header">
          <div>
            <h2>구역 목록</h2>
            <span>mock prototype 데이터 기준</span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>구역 이름</th>
                <th>구역 유형</th>
                <th>체류 기준</th>
                <th>알림</th>
                <th>좌표 기준</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((zone) => (
                <tr key={zone.zone_id}>
                  <td>{zone.number}</td>
                  <td>{zone.zone_name}</td>
                  <td>
                    <span className={`zone-type-pill ${getZoneClass(zone.zone_type)}`}>
                      {zone.zone_type}
                    </span>
                  </td>
                  <td>{zone.dwell_threshold_sec}초</td>
                  <td>{zone.alert_enabled ? "ON" : "OFF"}</td>
                  <td>{COORDINATE_BASIS}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
