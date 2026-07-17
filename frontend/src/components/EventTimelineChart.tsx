import { useMemo } from "react";
import type { SafetyEvent } from "../types/event";

interface EventTimelineChartProps {
  events: SafetyEvent[];
}

interface TimelineBucket {
  start: number;
  end: number;
  label: string;
  count: number;
}

const BUCKET_SECONDS = 10;
const CHART_WIDTH = 760;
const CHART_HEIGHT = 220;
const PADDING = {
  top: 18,
  right: 24,
  bottom: 42,
  left: 42,
};
const ABSOLUTE_TIMESTAMP_THRESHOLD_SECONDS = 365 * 24 * 60 * 60;

function parseTimestampToSeconds(timestamp: string) {
  const trimmed = timestamp.trim();
  const timeMatch = trimmed.match(/^(\d{1,2}):([0-5]\d):([0-5]\d)(?:\.(\d{1,3}))?$/);

  if (timeMatch) {
    const hours = Number(timeMatch[1]);
    const minutes = Number(timeMatch[2]);
    const seconds = Number(timeMatch[3]);
    const milliseconds = Number((timeMatch[4] ?? "0").padEnd(3, "0"));

    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000;
  }

  const parsedDate = Date.parse(trimmed);

  if (Number.isNaN(parsedDate)) {
    return null;
  }

  return parsedDate / 1000;
}

function padTime(value: number) {
  return String(value).padStart(2, "0");
}

function formatRelativeTime(totalSeconds: number) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const seconds = safeSeconds % 60;

  if (hours > 0) {
    return `${padTime(hours)}:${padTime(minutes)}:${padTime(seconds)}`;
  }

  return `${padTime(minutes)}:${padTime(seconds)}`;
}

function formatAbsoluteTime(totalSeconds: number) {
  return new Date(totalSeconds * 1000).toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatBucketLabel(start: number, end: number) {
  const isAbsolute = start > ABSOLUTE_TIMESTAMP_THRESHOLD_SECONDS;
  const formatter = isAbsolute ? formatAbsoluteTime : formatRelativeTime;

  return `${formatter(start)}~${formatter(end)}`;
}

function buildTimelineBuckets(events: SafetyEvent[]) {
  const parsedSeconds = events
    .map((event) => parseTimestampToSeconds(event.timestamp))
    .filter((seconds): seconds is number => seconds !== null && Number.isFinite(seconds));

  if (parsedSeconds.length === 0) {
    return [];
  }

  const bucketCounts = new Map<number, number>();
  const bucketStarts = parsedSeconds.map((seconds) =>
    Math.floor(seconds / BUCKET_SECONDS) * BUCKET_SECONDS,
  );
  const minBucketStart = Math.min(...bucketStarts);
  const maxBucketStart = Math.max(...bucketStarts);
  const bucketCount = Math.floor((maxBucketStart - minBucketStart) / BUCKET_SECONDS) + 1;

  bucketStarts.forEach((bucketStart) => {
    bucketCounts.set(bucketStart, (bucketCounts.get(bucketStart) ?? 0) + 1);
  });

  return Array.from({ length: bucketCount }, (_, index) => {
    const start = minBucketStart + index * BUCKET_SECONDS;
    const end = start + BUCKET_SECONDS;

    return {
      start,
      end,
      label: formatBucketLabel(start, end),
      count: bucketCounts.get(start) ?? 0,
    };
  });
}

function shouldShowXAxisLabel(index: number, totalCount: number) {
  if (totalCount <= 4) {
    return true;
  }

  const middleIndex = Math.floor((totalCount - 1) / 2);

  return index === 0 || index === middleIndex || index === totalCount - 1;
}

function buildSmoothPath(points: Array<{ x: number; y: number }>) {
  if (points.length === 0) {
    return "";
  }

  if (points.length === 1) {
    return `M ${points[0].x} ${points[0].y}`;
  }

  return points.reduce((path, point, index) => {
    if (index === 0) {
      return `M ${point.x} ${point.y}`;
    }

    const previous = points[index - 1];
    const controlDistance = (point.x - previous.x) / 2;

    return `${path} C ${previous.x + controlDistance} ${previous.y}, ${
      point.x - controlDistance
    } ${point.y}, ${point.x} ${point.y}`;
  }, "");
}

export default function EventTimelineChart({ events }: EventTimelineChartProps) {
  const buckets = useMemo(() => buildTimelineBuckets(events), [events]);

  if (buckets.length === 0) {
    return (
      <section className="card timeline-card">
        <div className="panel-header">
          <div>
            <h2>시간대별 이벤트 발생 추이</h2>
            <span>이벤트 발생 시간을 기준으로 구간별 이벤트 수를 표시합니다.</span>
          </div>
          <span>Line Chart</span>
        </div>
        <div className="timeline-empty-state">표시할 이벤트 데이터가 없습니다.</div>
      </section>
    );
  }

  const plotWidth = CHART_WIDTH - PADDING.left - PADDING.right;
  const plotHeight = CHART_HEIGHT - PADDING.top - PADDING.bottom;
  const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 1);
  const yTicks = Array.from(new Set([0, Math.ceil(maxCount / 2), maxCount])).sort(
    (a, b) => a - b,
  );
  const getX = (index: number) =>
    buckets.length === 1
      ? PADDING.left + plotWidth / 2
      : PADDING.left + (index / (buckets.length - 1)) * plotWidth;
  const getY = (count: number) =>
    PADDING.top + plotHeight - (count / maxCount) * plotHeight;
  const pointCoordinates = buckets.map((bucket, index) => ({
    ...bucket,
    x: getX(index),
    y: getY(bucket.count),
  }));
  const linePath = buildSmoothPath(pointCoordinates);
  const baselineY = PADDING.top + plotHeight;
  const areaPath =
    pointCoordinates.length > 1
      ? `${linePath} L ${pointCoordinates[pointCoordinates.length - 1].x} ${baselineY} L ${pointCoordinates[0].x} ${baselineY} Z`
      : "";
  const totalCount = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  const peakCount = Math.max(...buckets.map((bucket) => bucket.count));

  return (
    <section className="card timeline-card">
      <div className="panel-header">
        <div>
          <h2>시간대별 이벤트 발생 추이</h2>
          <span>이벤트 발생 시간을 기준으로 구간별 이벤트 수를 표시합니다.</span>
        </div>
        <div className="timeline-summary">
          <span>총 {totalCount}건</span>
          <span>최고 {peakCount}건</span>
          <span>10초 단위</span>
        </div>
      </div>
      <div className="timeline-chart">
        <svg
          aria-label="시간대별 이벤트 발생 추이 Line Chart"
          role="img"
          viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        >
          {yTicks.map((tick) => {
            const y = getY(tick);

            return (
              <g key={tick}>
                <line
                  className="timeline-grid-line"
                  x1={PADDING.left}
                  x2={CHART_WIDTH - PADDING.right}
                  y1={y}
                  y2={y}
                />
                <text
                  className="timeline-axis-label"
                  textAnchor="end"
                  x={PADDING.left - 12}
                  y={y + 4}
                >
                  {tick}
                </text>
              </g>
            );
          })}

          <line
            className="timeline-axis-line"
            x1={PADDING.left}
            x2={CHART_WIDTH - PADDING.right}
            y1={PADDING.top + plotHeight}
            y2={PADDING.top + plotHeight}
          />
          <line
            className="timeline-axis-line"
            x1={PADDING.left}
            x2={PADDING.left}
            y1={PADDING.top}
            y2={PADDING.top + plotHeight}
          />

          {areaPath ? <path className="timeline-area" d={areaPath} /> : null}
          {buckets.length > 1 ? <path className="timeline-line" d={linePath} /> : null}

          {pointCoordinates.map((point, index) => (
            <circle
              aria-label={`${point.label}: ${point.count}건`}
              className="timeline-point"
              cx={point.x}
              cy={point.y}
              key={point.start}
              r={4}
            >
              <title>{`${point.label}: ${point.count}건`}</title>
            </circle>
          ))}

          {pointCoordinates.map((point, index) =>
            shouldShowXAxisLabel(index, pointCoordinates.length) ? (
              <text
                className="timeline-axis-label"
                key={`${point.start}-label`}
                textAnchor={index === 0 ? "start" : index === pointCoordinates.length - 1 ? "end" : "middle"}
                x={point.x}
                y={CHART_HEIGHT - 20}
              >
                {point.label}
              </text>
            ) : null,
          )}
        </svg>
      </div>
    </section>
  );
}
