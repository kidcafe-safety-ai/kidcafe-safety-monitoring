import { type ReactNode, useEffect, useState } from "react";
import { X } from "lucide-react";
import { getMockSystemSettings } from "../api/systemSettingsMockApi";
import type {
  GlobalAlertSettings,
  PrivacySharingSettings,
  ReportSettings,
  StoreOperationSettings,
  SystemSettingsMockData,
} from "../types/systemSettings";

interface SystemSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function cloneSettings(data: SystemSettingsMockData): SystemSettingsMockData {
  return JSON.parse(JSON.stringify(data)) as SystemSettingsMockData;
}

function SettingGroup({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="settings-group-card">
      <div className="settings-group-header">
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      <div className="settings-form">{children}</div>
    </section>
  );
}

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="settings-row">
      <div className="settings-row-copy">
        <strong>{label}</strong>
        <span>{description}</span>
      </div>
      <div className="settings-row-control">{children}</div>
    </div>
  );
}

function ToggleSwitch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      aria-pressed={checked}
      className={`settings-switch ${checked ? "on" : ""}`}
      onClick={() => onChange(!checked)}
      type="button"
    >
      <span />
      <strong>{checked ? "ON" : "OFF"}</strong>
    </button>
  );
}

function NumberInput({
  value,
  onChange,
  min = 0,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
}) {
  return (
    <input
      className="settings-input compact"
      min={min}
      onChange={(event) => onChange(Number(event.target.value))}
      type="number"
      value={value}
    />
  );
}

export default function SystemSettingsModal({
  isOpen,
  onClose,
}: SystemSettingsModalProps) {
  const [settings, setSettings] = useState<SystemSettingsMockData | null>(null);
  const [initialSettings, setInitialSettings] =
    useState<SystemSettingsMockData | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    getMockSystemSettings().then((response) => {
      setSettings(cloneSettings(response.data));
      setInitialSettings(cloneSettings(response.data));
      setSaveMessage(null);
    });
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const updateOperation = <K extends keyof StoreOperationSettings>(
    key: K,
    value: StoreOperationSettings[K],
  ) => {
    setSettings((current) =>
      current
        ? { ...current, operation: { ...current.operation, [key]: value } }
        : current,
    );
    setSaveMessage(null);
  };

  const updateAlerts = <K extends keyof GlobalAlertSettings>(
    key: K,
    value: GlobalAlertSettings[K],
  ) => {
    setSettings((current) =>
      current ? { ...current, alerts: { ...current.alerts, [key]: value } } : current,
    );
    setSaveMessage(null);
  };

  const updateReports = <K extends keyof ReportSettings>(
    key: K,
    value: ReportSettings[K],
  ) => {
    setSettings((current) =>
      current ? { ...current, reports: { ...current.reports, [key]: value } } : current,
    );
    setSaveMessage(null);
  };

  const updatePrivacy = <K extends keyof PrivacySharingSettings>(
    key: K,
    value: PrivacySharingSettings[K],
  ) => {
    setSettings((current) =>
      current ? { ...current, privacy: { ...current.privacy, [key]: value } } : current,
    );
    setSaveMessage(null);
  };

  const handleReset = () => {
    if (!initialSettings) {
      return;
    }

    setSettings(cloneSettings(initialSettings));
    setSaveMessage("mock 설정을 초기값으로 되돌렸습니다.");
  };

  const handleSave = () => {
    setSaveMessage("mock preview입니다. 실제 서버에는 저장되지 않습니다.");
  };

  if (!isOpen) {
    return null;
  }

  const operation = settings?.operation;
  const alerts = settings?.alerts;
  const reports = settings?.reports;
  const privacy = settings?.privacy;

  return (
    <div
      className="system-settings-overlay"
      onClick={onClose}
      role="presentation"
    >
      <section
        aria-label="시스템 설정"
        aria-modal="true"
        className="system-settings-drawer"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="system-settings-header">
          <div>
            <div className="title-row">
              <h1>시스템 설정</h1>
              <span className="status-pill">Mock Prototype</span>
            </div>
            <p>매장 운영과 알림, 리포트 공유 기준을 관리합니다.</p>
          </div>
          <button
            aria-label="시스템 설정 닫기"
            className="settings-close-button"
            onClick={onClose}
            type="button"
          >
            <X size={18} strokeWidth={2.2} />
          </button>
        </header>

        <div className="system-settings-body single-form">
          <div className="settings-content">
            {settings && operation && alerts && reports && privacy ? (
              <div className="settings-simple-form">
                <SettingGroup
                  description="운영 시간과 기본 수용 기준을 설정합니다."
                  title="매장 운영"
                >
                  <SettingRow
                    description="대시보드와 보호자 공유 리포트에 표시되는 이름입니다."
                    label="매장 이름"
                  >
                    <input
                      className="settings-input"
                      onChange={(event) =>
                        updateOperation("store_name", event.target.value)
                      }
                      value={operation.store_name}
                    />
                  </SettingRow>
                  <SettingRow
                    description="운영 통계와 리포트 기준 시작 시간입니다."
                    label="운영 시작 시간"
                  >
                    <input
                      className="settings-input compact"
                      onChange={(event) =>
                        updateOperation("operation_start", event.target.value)
                      }
                      type="time"
                      value={operation.operation_start}
                    />
                  </SettingRow>
                  <SettingRow
                    description="운영 통계와 리포트 기준 종료 시간입니다."
                    label="운영 종료 시간"
                  >
                    <input
                      className="settings-input compact"
                      onChange={(event) =>
                        updateOperation("operation_end", event.target.value)
                      }
                      type="time"
                      value={operation.operation_end}
                    />
                  </SettingRow>
                  <SettingRow
                    description="매장 전체 동시 이용 인원 기준입니다."
                    label="최대 수용 인원"
                  >
                    <NumberInput
                      onChange={(value) => updateOperation("max_capacity", value)}
                      value={operation.max_capacity}
                    />
                  </SettingRow>
                  <SettingRow
                    description="해당 인원 이상이면 혼잡 상태로 표시합니다."
                    label="혼잡 기준"
                  >
                    <NumberInput
                      onChange={(value) => updateOperation("crowd_threshold", value)}
                      value={operation.crowd_threshold}
                    />
                  </SettingRow>
                </SettingGroup>

                <SettingGroup
                  description="위험 상황을 직원에게 알리는 방식을 설정합니다."
                  title="알림 설정"
                >
                  <SettingRow
                    description="위험구역 체류나 접근 이벤트 발생 시 알림을 표시합니다."
                    label="위험 알림 사용"
                  >
                    <ToggleSwitch
                      checked={alerts.risk_alert_enabled}
                      onChange={(checked) =>
                        updateAlerts("risk_alert_enabled", checked)
                      }
                    />
                  </SettingRow>
                  <SettingRow
                    description="직원이 놓치지 않도록 알림음을 함께 재생합니다."
                    label="알림음 사용"
                  >
                    <ToggleSwitch
                      checked={alerts.sound_enabled}
                      onChange={(checked) => updateAlerts("sound_enabled", checked)}
                    />
                  </SettingRow>
                  <SettingRow
                    description="중요 알림을 대시보드 화면에 팝업으로 표시합니다."
                    label="화면 팝업 알림 사용"
                  >
                    <ToggleSwitch
                      checked={alerts.popup_enabled}
                      onChange={(checked) => updateAlerts("popup_enabled", checked)}
                    />
                  </SettingRow>
                  <SettingRow
                    description="확인되지 않은 알림을 다시 띄우는 간격입니다."
                    label="반복 알림 간격"
                  >
                    <select
                      className="settings-input compact"
                      onChange={(event) =>
                        updateAlerts(
                          "repeat_interval_minutes",
                          Number(event.target.value),
                        )
                      }
                      value={alerts.repeat_interval_minutes}
                    >
                      {[1, 3, 5, 10].map((minute) => (
                        <option key={minute} value={minute}>
                          {minute}분
                        </option>
                      ))}
                    </select>
                  </SettingRow>
                  <SettingRow
                    description="같은 구역에 오래 머무를 때 알림으로 볼 기준입니다."
                    label="장기 체류 기준"
                  >
                    <select
                      className="settings-input compact"
                      onChange={(event) =>
                        updateAlerts("auto_clear_minutes", Number(event.target.value))
                      }
                      value={alerts.auto_clear_minutes}
                    >
                      {[5, 10, 15, 20].map((minute) => (
                        <option key={minute} value={minute}>
                          {minute}분
                        </option>
                      ))}
                    </select>
                  </SettingRow>
                </SettingGroup>

                <SettingGroup
                  description="보호자 공유 리포트와 개인정보 표시 기준을 설정합니다."
                  title="리포트 / 개인정보"
                >
                  <SettingRow
                    description="운영 종료 후 일일 리포트를 자동으로 준비합니다."
                    label="일일 리포트 자동 생성"
                  >
                    <ToggleSwitch
                      checked={reports.daily_auto_enabled}
                      onChange={(checked) =>
                        updateReports("daily_auto_enabled", checked)
                      }
                    />
                  </SettingRow>
                  <SettingRow
                    description="일일 리포트가 준비되는 기준 시간입니다."
                    label="리포트 생성 시간"
                  >
                    <input
                      className="settings-input compact"
                      onChange={(event) =>
                        updateReports("generation_time", event.target.value)
                      }
                      type="time"
                      value={reports.generation_time}
                    />
                  </SettingRow>
                  <SettingRow
                    description="보호자 공유 화면에서 아동 정보를 익명화합니다."
                    label="아동 정보 익명화"
                  >
                    <ToggleSwitch
                      checked={privacy.anonymize_child_id}
                      onChange={(checked) =>
                        updatePrivacy("anonymize_child_id", checked)
                      }
                    />
                  </SettingRow>
                  <SettingRow
                    description="보호자 공유 화면에 함께 표시되는 안내 문구입니다."
                    label="보호자 공유 문구"
                  >
                    <textarea
                      className="settings-textarea"
                      onChange={(event) =>
                        updateReports("guardian_share_message", event.target.value)
                      }
                      value={reports.guardian_share_message}
                    />
                  </SettingRow>
                </SettingGroup>
              </div>
            ) : (
              <div className="state-banner">설정 정보를 불러오는 중입니다.</div>
            )}
          </div>
        </div>

        <footer className="system-settings-footer">
          <div className="system-settings-footer-copy">
            <span>Mock preview입니다. 저장 동작은 실제 서버에 반영되지 않습니다.</span>
            {saveMessage ? <strong>{saveMessage}</strong> : null}
          </div>
          <div className="system-settings-footer-actions">
            <button onClick={onClose} type="button">
              취소
            </button>
            <button onClick={handleReset} type="button">
              변경 초기화
            </button>
            <button className="primary" onClick={handleSave} type="button">
              저장
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
