import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent,
} from "react";
import { getZones, putZones } from "../api/zoneSettingsApi";
import type {
  Zone,
  ZoneApiErrorType,
  ZoneApiResponse,
  ZoneConfig,
  ZonePoint,
  ZoneType,
} from "../types/zoneSettings";
import { validateZones, type ZoneValidationIssue } from "../utils/zoneValidation";

type LoadState = "idle" | "loading" | "success" | "empty" | "error";
type SaveState = "idle" | "saving" | "success" | "error" | "conflict";
type EditableZoneField = "zone_id" | "zone_name" | "zone_type";

const ZONE_TYPE_LABELS: Record<ZoneType, string> = {
  play: "놀이구역",
  exit: "출입구",
  restricted: "제한구역",
  danger: "위험구역",
};

const ZONE_TYPES: ZoneType[] = ["play", "exit", "restricted", "danger"];

function getZoneClass(zoneType: ZoneType) {
  if (zoneType === "danger") {
    return "zone-danger";
  }

  if (zoneType === "restricted" || zoneType === "exit") {
    return "zone-warning";
  }

  return "zone-watch";
}

function formatPoints(points: ZonePoint[]) {
  return points.map(([x, y]) => `${x * 100},${y * 100}`).join(" ");
}

function cloneZone(zone: Zone): Zone {
  return {
    ...zone,
    points: zone.points.map(([x, y]) => [x, y]),
    rules: { ...zone.rules },
  };
}

function cloneZones(zones: Zone[]) {
  return zones.map(cloneZone);
}

function serializeZones(zones: Zone[]) {
  return JSON.stringify(zones);
}

function createEmptyZone(existingZones: Zone[]): Zone {
  const existingIds = new Set(existingZones.map((zone) => zone.zone_id));
  let nextIndex = existingZones.length + 1;
  let zoneId = `zone_${nextIndex}`;

  while (existingIds.has(zoneId)) {
    nextIndex += 1;
    zoneId = `zone_${nextIndex}`;
  }

  return {
    zone_id: zoneId,
    zone_name: `새 구역 ${nextIndex}`,
    type: "polygon",
    zone_type: "play",
    points: [
      [0.1, 0.1],
      [0.3, 0.1],
      [0.3, 0.3],
      [0.1, 0.3],
    ],
    rules: {
      enter_alert: false,
      dwell_threshold_sec: 0,
    },
  };
}

function normalizeNumberInput(value: string) {
  if (value.trim().length === 0) {
    return Number.NaN;
  }

  return Number(value);
}

function prepareZonesForSave(zones: Zone[]) {
  return zones.map((zone) => ({
    ...zone,
    zone_id: zone.zone_id.trim(),
    zone_name: zone.zone_name.trim(),
    type: "polygon" as const,
    points: zone.points.map(([x, y]) => [x, y] as ZonePoint),
    rules: {
      enter_alert: zone.rules.enter_alert,
      dwell_threshold_sec: Math.trunc(zone.rules.dwell_threshold_sec),
    },
  }));
}

function getSafeErrorMessage(response: ZoneApiResponse<ZoneConfig>) {
  if (response.error_type === "conflict") {
    return "다른 사용자가 Zone 설정을 먼저 변경했습니다. 서버의 최신 설정을 불러왔습니다. 기존 변경 내용을 다시 확인한 후 저장해 주세요.";
  }

  if (response.error_type === "validation") {
    return response.message ?? "Zone schema 또는 polygon validation에 실패했습니다.";
  }

  if (response.error_type === "network") {
    return "API 연결에 실패했습니다. Zone 설정을 처리할 수 없습니다.";
  }

  if (response.error_type === "schema") {
    return "Zone 설정 응답 형식이 올바르지 않습니다.";
  }

  return response.message ?? "Zone 설정 요청에 실패했습니다.";
}

function getIssuesForZone(issues: ZoneValidationIssue[], zoneIndex: number) {
  return issues.filter((issue) => issue.zoneIndex === zoneIndex);
}

function hasIssue(issues: ZoneValidationIssue[], field: string) {
  return issues.some((issue) => issue.field === field || issue.field.startsWith(`${field}.`));
}

function roundNormalizedCoordinate(value: number) {
  return Math.round(value * 10000) / 10000;
}

function getContainedVideoBounds(
  containerRect: DOMRect,
  videoElement: HTMLVideoElement | null,
) {
  if (
    videoElement === null ||
    videoElement.videoWidth <= 0 ||
    videoElement.videoHeight <= 0
  ) {
    return {
      left: containerRect.left,
      top: containerRect.top,
      width: containerRect.width,
      height: containerRect.height,
    };
  }

  const videoAspectRatio = videoElement.videoWidth / videoElement.videoHeight;
  const containerAspectRatio = containerRect.width / containerRect.height;

  if (videoAspectRatio > containerAspectRatio) {
    const height = containerRect.width / videoAspectRatio;

    return {
      left: containerRect.left,
      top: containerRect.top + (containerRect.height - height) / 2,
      width: containerRect.width,
      height,
    };
  }

  const width = containerRect.height * videoAspectRatio;

  return {
    left: containerRect.left + (containerRect.width - width) / 2,
    top: containerRect.top,
    width,
    height: containerRect.height,
  };
}

export default function ZoneSettingsPage() {
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [config, setConfig] = useState<ZoneConfig | null>(null);
  const [draftZones, setDraftZones] = useState<Zone[]>([]);
  const [selectedZoneIndex, setSelectedZoneIndex] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveDetails, setSaveDetails] = useState<string[]>([]);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [conflictDraft, setConflictDraft] = useState<Zone[] | null>(null);
  const [referenceVideoUrl, setReferenceVideoUrl] = useState<string | null>(null);
  const [referenceVideoName, setReferenceVideoName] = useState<string | null>(null);
  const [referenceVideoAspectRatio, setReferenceVideoAspectRatio] = useState<string | null>(
    null,
  );
  const loadRequestIdRef = useRef(0);
  const loadAbortControllerRef = useRef<AbortController | null>(null);
  const saveAbortControllerRef = useRef<AbortController | null>(null);
  const referenceVideoUrlRef = useRef<string | null>(null);
  const referenceVideoRef = useRef<HTMLVideoElement | null>(null);
  const referenceVideoInputRef = useRef<HTMLInputElement | null>(null);

  const validationIssues = useMemo(() => validateZones(draftZones), [draftZones]);
  const originalZones = config?.zones ?? [];
  const hasUnsavedChanges =
    config !== null && serializeZones(draftZones) !== serializeZones(originalZones);
  const safeSelectedZoneIndex =
    draftZones.length === 0
      ? -1
      : Math.min(Math.max(selectedZoneIndex, 0), draftZones.length - 1);
  const selectedZone =
    safeSelectedZoneIndex >= 0 ? draftZones[safeSelectedZoneIndex] : null;
  const selectedIndex = safeSelectedZoneIndex >= 0 ? safeSelectedZoneIndex : 0;
  const selectedZoneIssues = getIssuesForZone(validationIssues, selectedIndex);
  const isLoading = loadState === "loading";
  const isSaving = saveState === "saving";
  const isLoadFailed = loadState === "error";
  const isEditingDisabled = isLoading || isSaving || isLoadFailed;
  const canEditSelectedZone = selectedZone !== null && !isEditingDisabled;
  const hasSelectedZonePoints = selectedZone !== null && selectedZone.points.length > 0;
  const canSave =
    config !== null &&
    !isEditingDisabled &&
    hasUnsavedChanges &&
    validationIssues.length === 0;

  const applyLoadedConfig = useCallback((nextConfig: ZoneConfig) => {
    const nextZones = cloneZones(nextConfig.zones);

    setConfig({ ...nextConfig, zones: nextZones });
    setDraftZones(cloneZones(nextZones));
    setSelectedZoneIndex(0);
    setLoadState(nextZones.length === 0 ? "empty" : "success");
    setLoadError(null);
  }, []);

  const loadZoneSettings = useCallback(
    async (options?: { keepMessages?: boolean }) => {
      loadAbortControllerRef.current?.abort();
      const requestId = loadRequestIdRef.current + 1;
      const controller = new AbortController();
      loadRequestIdRef.current = requestId;
      loadAbortControllerRef.current = controller;

      setLoadState("loading");
      setLoadError(null);

      if (!options?.keepMessages) {
        setSaveError(null);
        setSaveDetails([]);
        setSuccessMessage(null);
      }

      const response = await getZones({ signal: controller.signal });

      if (controller.signal.aborted || loadRequestIdRef.current !== requestId) {
        return null;
      }

      if (response.status === "success" && response.data !== null) {
        applyLoadedConfig(response.data);
        return response.data;
      }

      setConfig(null);
      setDraftZones([]);
      setSelectedZoneIndex(0);
      setLoadState("error");
      setLoadError(getSafeErrorMessage(response));

      return null;
    },
    [applyLoadedConfig],
  );

  useEffect(() => {
    void loadZoneSettings();

    return () => {
      loadAbortControllerRef.current?.abort();
      saveAbortControllerRef.current?.abort();
    };
  }, [loadZoneSettings]);

  useEffect(
    () => () => {
      if (referenceVideoUrlRef.current !== null) {
        URL.revokeObjectURL(referenceVideoUrlRef.current);
      }
    },
    [],
  );

  const handleReload = async () => {
    if (
      hasUnsavedChanges &&
      !window.confirm("저장하지 않은 변경 내용이 있습니다. 다시 불러오시겠습니까?")
    ) {
      return;
    }

    await loadZoneSettings();
  };

  const updateZoneAt = (zoneIndex: number, updater: (zone: Zone) => Zone) => {
    setDraftZones((zones) =>
      zones.map((zone, index) => (index === zoneIndex ? updater(zone) : zone)),
    );
    setSaveError(null);
    setSuccessMessage(null);
  };

  const handleZoneFieldChange = (
    zoneIndex: number,
    field: EditableZoneField,
    value: string,
  ) => {
    updateZoneAt(zoneIndex, (zone) => ({
      ...zone,
      [field]: field === "zone_type" ? (value as ZoneType) : value,
    }));
  };

  const handlePointChange = (
    zoneIndex: number,
    pointIndex: number,
    axis: 0 | 1,
    value: string,
  ) => {
    const nextValue = normalizeNumberInput(value);

    updateZoneAt(zoneIndex, (zone) => ({
      ...zone,
      points: zone.points.map((point, index) =>
        index === pointIndex
          ? ([axis === 0 ? nextValue : point[0], axis === 1 ? nextValue : point[1]] as ZonePoint)
          : point,
      ),
    }));
  };

  const handleAddPoint = (zoneIndex: number) => {
    updateZoneAt(zoneIndex, (zone) => ({
      ...zone,
      points: [...zone.points, [0.5, 0.5]],
    }));
  };

  const handleRemovePoint = (zoneIndex: number, pointIndex: number) => {
    updateZoneAt(zoneIndex, (zone) => ({
      ...zone,
      points: zone.points.filter((_, index) => index !== pointIndex),
    }));
  };

  const handleRuleChange = (
    zoneIndex: number,
    field: keyof Zone["rules"],
    value: boolean | number,
  ) => {
    updateZoneAt(zoneIndex, (zone) => ({
      ...zone,
      rules: {
        ...zone.rules,
        [field]: value,
      },
    }));
  };

  const handleAddZone = () => {
    setDraftZones((zones) => {
      const nextZone = createEmptyZone(zones);

      setSelectedZoneIndex(zones.length);
      return [...zones, nextZone];
    });
    setSaveError(null);
    setSuccessMessage(null);
  };

  const handleRemoveZone = (zoneIndex: number) => {
    const zone = draftZones[zoneIndex];

    if (!zone) {
      return;
    }

    if (!window.confirm(`${zone.zone_name || zone.zone_id} 구역을 삭제하시겠습니까?`)) {
      return;
    }

    setDraftZones((zones) => {
      const nextZones = zones.filter((_, index) => index !== zoneIndex);
      setSelectedZoneIndex(
        nextZones.length === 0 ? 0 : Math.min(zoneIndex, nextZones.length - 1),
      );
      return nextZones;
    });
    setSaveError(null);
    setSuccessMessage(null);
  };

  const handleRestoreConflictDraft = () => {
    if (conflictDraft === null) {
      return;
    }

    setDraftZones(cloneZones(conflictDraft));
    setSelectedZoneIndex(0);
    setConflictDraft(null);
    setSaveState("error");
    setSaveError(
      "보존된 미저장 draft를 다시 적용했습니다. 서버 최신 설정 기준으로 다시 확인한 뒤 저장해 주세요.",
    );
    setSaveDetails([]);
    setSuccessMessage(null);
  };

  const handleReferenceVideoChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;

    if (referenceVideoUrlRef.current !== null) {
      URL.revokeObjectURL(referenceVideoUrlRef.current);
      referenceVideoUrlRef.current = null;
    }

    if (file === null) {
      setReferenceVideoUrl(null);
      setReferenceVideoName(null);
      setReferenceVideoAspectRatio(null);
      return;
    }

    const nextUrl = URL.createObjectURL(file);
    referenceVideoUrlRef.current = nextUrl;
    setReferenceVideoUrl(nextUrl);
    setReferenceVideoName(file.name);
    setReferenceVideoAspectRatio(null);
  };

  const handleClearReferenceVideo = () => {
    if (referenceVideoUrlRef.current !== null) {
      URL.revokeObjectURL(referenceVideoUrlRef.current);
      referenceVideoUrlRef.current = null;
    }

    setReferenceVideoUrl(null);
    setReferenceVideoName(null);
    setReferenceVideoAspectRatio(null);

    if (referenceVideoInputRef.current !== null) {
      referenceVideoInputRef.current.value = "";
    }
  };

  const handleReferenceVideoLoadedMetadata = () => {
    const videoElement = referenceVideoRef.current;

    if (
      videoElement === null ||
      videoElement.videoWidth <= 0 ||
      videoElement.videoHeight <= 0
    ) {
      setReferenceVideoAspectRatio(null);
      return;
    }

    setReferenceVideoAspectRatio(
      `${videoElement.videoWidth} / ${videoElement.videoHeight}`,
    );
  };

  const handlePlayReferenceVideo = () => {
    const playPromise = referenceVideoRef.current?.play();

    if (playPromise) {
      void playPromise.catch(() => undefined);
    }
  };

  const handlePauseReferenceVideo = () => {
    referenceVideoRef.current?.pause();
  };

  const handleReferenceFrameClick = (event: MouseEvent<HTMLDivElement>) => {
    if (referenceVideoUrl === null || !canEditSelectedZone) {
      return;
    }

    const bounds = getContainedVideoBounds(
      event.currentTarget.getBoundingClientRect(),
      referenceVideoRef.current,
    );

    const x = (event.clientX - bounds.left) / bounds.width;
    const y = (event.clientY - bounds.top) / bounds.height;

    if (x < 0 || x > 1 || y < 0 || y > 1) {
      return;
    }

    updateZoneAt(selectedIndex, (zone) => ({
      ...zone,
      points: [
        ...zone.points,
        [roundNormalizedCoordinate(x), roundNormalizedCoordinate(y)],
      ],
    }));
  };

  const handleUndoLastPoint = () => {
    if (!canEditSelectedZone) {
      return;
    }

    updateZoneAt(selectedIndex, (zone) => ({
      ...zone,
      points: zone.points.slice(0, -1),
    }));
  };

  const handleClearSelectedPoints = () => {
    if (!canEditSelectedZone) {
      return;
    }

    updateZoneAt(selectedIndex, (zone) => ({
      ...zone,
      points: [],
    }));
  };

  const handleSave = async () => {
    if (config === null || isSaving) {
      return;
    }

    const zonesToSave = prepareZonesForSave(draftZones);
    const nextValidationIssues = validateZones(zonesToSave);

    if (nextValidationIssues.length > 0) {
      setSaveState("error");
      setSaveError("입력값 validation을 먼저 해결해 주세요.");
      setSaveDetails(nextValidationIssues.slice(0, 5).map((issue) => issue.message));
      return;
    }

    setSaveState("saving");
    setSaveError(null);
    setSaveDetails([]);
    setSuccessMessage(null);
    setConflictDraft(null);

    saveAbortControllerRef.current?.abort();
    const saveController = new AbortController();
    saveAbortControllerRef.current = saveController;

    const response = await putZones({
      expected_version: config.version,
      zones: zonesToSave,
    }, { signal: saveController.signal });

    if (saveController.signal.aborted) {
      return;
    }

    if (response.status === "success" && response.data !== null) {
      applyLoadedConfig(response.data);
      setSaveState("success");
      setSuccessMessage("Zone 설정이 저장되었습니다. Vision AI 재시작 후 적용됩니다.");
      return;
    }

    if (response.error_type === "conflict") {
      setSaveState("conflict");
      setConflictDraft(cloneZones(draftZones));
      setSaveError(getSafeErrorMessage(response));
      setSaveDetails([
        "기존 변경 내용은 자동 저장되지 않았습니다.",
        "서버 최신 설정을 확인한 뒤 다시 수정·저장해 주세요.",
      ]);
      await loadZoneSettings({ keepMessages: true });
      return;
    }

    setSaveState("error");
    setSaveError(getSafeErrorMessage(response));
    setSaveDetails(response.details ?? []);
  };

  return (
    <section className="page zone-settings-page">
      <div className="page-heading">
        <div>
          <div className="title-row">
            <h1>안전구역 / 알림 설정</h1>
            <span className="status-pill">안전구역 관리</span>
          </div>
        </div>
      </div>

      {isLoading ? <div className="state-banner">Zone 설정을 불러오는 중입니다.</div> : null}
      {loadError ? (
        <div className="state-banner error zone-state-panel">
          <strong>Zone 설정을 불러올 수 없습니다.</strong>
          <span>{loadError}</span>
          <button onClick={handleReload} type="button">
            재시도
          </button>
        </div>
      ) : null}
      {loadState === "empty" && !loadError ? (
        <div className="state-banner empty zone-state-panel">
          <strong>저장된 Zone이 없습니다.</strong>
          <span>빈 Zone 설정은 정상 상태입니다. 새 Zone을 추가해 저장할 수 있습니다.</span>
        </div>
      ) : null}
      {saveError ? (
        <div className={`state-banner ${saveState === "conflict" ? "" : "error"} zone-state-panel`}>
          <strong>{saveError}</strong>
          {saveDetails.map((detail) => (
            <span key={detail}>{detail}</span>
          ))}
          {conflictDraft ? (
            <>
              <span>보존된 미저장 draft: {conflictDraft.length}개 Zone</span>
              <button onClick={handleRestoreConflictDraft} type="button">
                내 변경 다시 적용
              </button>
            </>
          ) : null}
        </div>
      ) : null}
      {successMessage ? (
        <div className="state-banner success zone-state-panel">
          <strong>{successMessage}</strong>
        </div>
      ) : null}

      <div className="zone-toolbar card">
        <div>
          <span>저장 상태</span>
          <strong>{hasUnsavedChanges ? "저장 안 됨" : "저장됨"}</strong>
        </div>
        <div className="zone-toolbar-actions">
          <button disabled={isLoading || isSaving} onClick={handleReload} type="button">
            다시 불러오기
          </button>
          <button disabled={isEditingDisabled} onClick={handleAddZone} type="button">
            Zone 추가
          </button>
        </div>
      </div>

      <div className="zone-settings-grid">
        <section className="card zone-preview-card">
          <div className="panel-header">
            <div>
              <h2>영상 프레임 미리보기</h2>
              <span>촬영 영상을 보며 마우스로 구역 꼭짓점을 설정합니다.</span>
            </div>
          </div>
          <div className="zone-reference-tools">
            <label className="zone-video-file-picker">
              <span>로컬 촬영 영상 선택</span>
              <input
                accept="video/*"
                onChange={handleReferenceVideoChange}
                ref={referenceVideoInputRef}
                type="file"
              />
            </label>
            <div className="zone-video-controls">
              <button
                disabled={referenceVideoUrl === null}
                onClick={handlePlayReferenceVideo}
                type="button"
              >
                재생
              </button>
              <button
                disabled={referenceVideoUrl === null}
                onClick={handlePauseReferenceVideo}
                type="button"
              >
                일시정지
              </button>
              <button
                disabled={referenceVideoUrl === null}
                onClick={handleClearReferenceVideo}
                type="button"
              >
                영상 제거
              </button>
            </div>
          </div>
          <div className="zone-map">
            <div
              className={`video-frame-preview ${referenceVideoUrl ? "has-reference-video" : ""} ${
                referenceVideoUrl && canEditSelectedZone ? "is-clickable" : ""
              }`}
              onClick={handleReferenceFrameClick}
              style={
                referenceVideoAspectRatio
                  ? { aspectRatio: referenceVideoAspectRatio }
                  : undefined
              }
            >
              {referenceVideoUrl ? (
                <video
                  className="zone-reference-video"
                  muted
                  onLoadedMetadata={handleReferenceVideoLoadedMetadata}
                  playsInline
                  ref={referenceVideoRef}
                  src={referenceVideoUrl}
                />
              ) : null}
              <div className="video-hud top-left">
                <strong>{referenceVideoUrl ? "VIDEO" : "ZONE"}</strong>
                <span>{referenceVideoName ?? "normalized"}</span>
              </div>
              <div className="video-hud top-right">
                <strong>{draftZones.length} zones</strong>
                <span>
                  {selectedZone ? `${selectedZone.points.length} points` : "구역 선택"}
                </span>
              </div>
              <div className="video-guide horizontal" />
              <div className="video-guide vertical" />
              <svg
                aria-label="영상 프레임 Zone polygon"
                className="zone-overlay"
                viewBox="0 0 100 100"
              >
                {draftZones.map((zone, index) => {
                  const points = formatPoints(zone.points);

                  return (
                    <g
                      className={`${getZoneClass(zone.zone_type)} ${
                        selectedIndex === index ? "selected-zone" : ""
                      }`}
                      key={`${index}-${zone.zone_id}`}
                    >
                      {zone.points.length >= 3 ? (
                        <polygon points={points} />
                      ) : zone.points.length > 1 ? (
                        <polyline points={points} />
                      ) : null}
                      {zone.points.map(([x, y], pointIndex) => (
                        <circle
                          cx={x * 100}
                          cy={y * 100}
                          key={`${zone.zone_id}-${pointIndex}`}
                          r="1.5"
                        />
                      ))}
                      {zone.points[0] ? (
                        <text x={zone.points[0][0] * 100 + 2} y={zone.points[0][1] * 100 + 8}>
                          {zone.zone_name || zone.zone_id}
                        </text>
                      ) : null}
                    </g>
                  );
                })}
              </svg>
            </div>
          </div>
          <div className="zone-click-actions">
            <div>
              <strong>{selectedZone ? selectedZone.zone_name || selectedZone.zone_id : "구역 선택"}</strong>
              <span>
                영상을 일시정지한 뒤 꼭짓점을 순서대로 클릭하세요. 좌표는 아래에서 세부 조정할 수 있습니다.
              </span>
            </div>
            <div>
              <button
                disabled={!canEditSelectedZone || !hasSelectedZonePoints}
                onClick={handleUndoLastPoint}
                type="button"
              >
                마지막 점 취소
              </button>
              <button
                disabled={!canEditSelectedZone || !hasSelectedZonePoints}
                onClick={handleClearSelectedPoints}
                type="button"
              >
                전체 초기화
              </button>
              <button disabled={!canSave} onClick={handleSave} type="button">
                {isSaving ? "저장 중..." : "구역 저장"}
              </button>
            </div>
          </div>
          <p className="zone-reference-note">
            선택한 영상은 서버에 업로드되지 않으며 브라우저 안에서만 사용됩니다.
          </p>
        </section>

        <section className="card zone-config-card">
          <div className="panel-header">
            <div>
              <h2>선택 구역 설정</h2>
              <span>선택한 구역의 이름, 종류, 알림 기준을 설정합니다.</span>
            </div>
          </div>

          {selectedZone ? (
            <div className="zone-form-preview editable-zone-form">
              <label className={hasIssue(selectedZoneIssues, "zone_id") ? "invalid" : ""}>
                <span>구역 ID</span>
                <input
                  disabled={isEditingDisabled}
                  onChange={(event) =>
                    handleZoneFieldChange(selectedIndex, "zone_id", event.target.value)
                  }
                  value={selectedZone.zone_id}
                />
              </label>
              <label className={hasIssue(selectedZoneIssues, "zone_name") ? "invalid" : ""}>
                <span>구역 이름</span>
                <input
                  disabled={isEditingDisabled}
                  onChange={(event) =>
                    handleZoneFieldChange(selectedIndex, "zone_name", event.target.value)
                  }
                  value={selectedZone.zone_name}
                />
              </label>
              <label>
                <span>구역 종류</span>
                <select
                  disabled={isEditingDisabled}
                  onChange={(event) =>
                    handleZoneFieldChange(selectedIndex, "zone_type", event.target.value)
                  }
                  value={selectedZone.zone_type}
                >
                  {ZONE_TYPES.map((zoneType) => (
                    <option key={zoneType} value={zoneType}>
                      {ZONE_TYPE_LABELS[zoneType]} ({zoneType})
                    </option>
                  ))}
                </select>
              </label>
              <label
                className={
                  hasIssue(selectedZoneIssues, "rules.dwell_threshold_sec") ? "invalid" : ""
                }
              >
                <span>체류 알림 기준 시간(초)</span>
                <input
                  disabled={isEditingDisabled}
                  max={3600}
                  min={0}
                  onChange={(event) =>
                    handleRuleChange(
                      selectedIndex,
                      "dwell_threshold_sec",
                      normalizeNumberInput(event.target.value),
                    )
                  }
                  type="number"
                  value={Number.isFinite(selectedZone.rules.dwell_threshold_sec)
                    ? selectedZone.rules.dwell_threshold_sec
                    : ""}
                />
              </label>
              <div className="setting-row">
                <span>진입 알림</span>
                <label className="zone-checkbox-row">
                  <input
                    checked={selectedZone.rules.enter_alert}
                    disabled={isEditingDisabled}
                    onChange={(event) =>
                      handleRuleChange(selectedIndex, "enter_alert", event.target.checked)
                    }
                    type="checkbox"
                  />
                  <strong>{selectedZone.rules.enter_alert ? "ON" : "OFF"}</strong>
                </label>
              </div>
              <div className="zone-field-errors">
                {selectedZoneIssues.map((issue, index) => (
                  <span key={`${issue.field}-${index}`}>{issue.message}</span>
                ))}
              </div>
            </div>
          ) : (
            <div className="table-empty-state">선택된 Zone이 없습니다.</div>
          )}
        </section>
      </div>

      <section className="card zone-table-card">
        <div className="panel-header">
          <div>
            <h2>구역 목록</h2>
            <span>PUT /zones 저장 시 현재 목록 전체가 전송됩니다.</span>
          </div>
          <span>{draftZones.length}개</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>zone_id</th>
                <th>zone_name</th>
                <th>zone_type</th>
                <th>points</th>
                <th>enter_alert</th>
                <th>dwell</th>
                <th>상태</th>
                <th>작업</th>
              </tr>
            </thead>
            <tbody>
              {draftZones.map((zone, index) => {
                const zoneIssues = getIssuesForZone(validationIssues, index);

                return (
                  <tr
                    className={selectedIndex === index ? "selected-row" : ""}
                    key={`${index}-${zone.zone_id}`}
                    onClick={() => setSelectedZoneIndex(index)}
                  >
                    <td>{index + 1}</td>
                    <td>{zone.zone_id || "-"}</td>
                    <td>{zone.zone_name || "-"}</td>
                    <td>
                      <span className={`zone-type-pill ${getZoneClass(zone.zone_type)}`}>
                        {ZONE_TYPE_LABELS[zone.zone_type]}
                      </span>
                    </td>
                    <td>{zone.points.length}</td>
                    <td>{zone.rules.enter_alert ? "ON" : "OFF"}</td>
                    <td>{zone.rules.dwell_threshold_sec}초</td>
                    <td>{zoneIssues.length > 0 ? `${zoneIssues.length}개 오류` : "정상"}</td>
                    <td>
                      <button
                        disabled={isEditingDisabled}
                        onClick={(event) => {
                          event.stopPropagation();
                          handleRemoveZone(index);
                        }}
                        type="button"
                      >
                        삭제
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {selectedZone ? (
        <section className="card zone-table-card zone-points-card">
          <div className="panel-header">
            <div>
              <h2>Polygon Points</h2>
              <span>x, y는 0.0 이상 1.0 이하 normalized coordinate입니다.</span>
            </div>
            <button
              disabled={isEditingDisabled}
              onClick={() => handleAddPoint(selectedIndex)}
              type="button"
            >
              Point 추가
            </button>
          </div>
          <div className="zone-points-grid">
            {selectedZone.points.map(([x, y], pointIndex) => (
              <div
                className={
                  hasIssue(selectedZoneIssues, `points.${pointIndex}`) ? "zone-point-row invalid" : "zone-point-row"
                }
                key={`${selectedZone.zone_id}-point-${pointIndex}`}
              >
                <strong>#{pointIndex + 1}</strong>
                <label>
                  <span>x</span>
                  <input
                    disabled={isEditingDisabled}
                    max={1}
                    min={0}
                    onChange={(event) =>
                      handlePointChange(selectedIndex, pointIndex, 0, event.target.value)
                    }
                    step={0.001}
                    type="number"
                    value={Number.isFinite(x) ? x : ""}
                  />
                </label>
                <label>
                  <span>y</span>
                  <input
                    disabled={isEditingDisabled}
                    max={1}
                    min={0}
                    onChange={(event) =>
                      handlePointChange(selectedIndex, pointIndex, 1, event.target.value)
                    }
                    step={0.001}
                    type="number"
                    value={Number.isFinite(y) ? y : ""}
                  />
                </label>
                <button
                  disabled={isEditingDisabled}
                  onClick={() => handleRemovePoint(selectedIndex, pointIndex)}
                  type="button"
                >
                  삭제
                </button>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
