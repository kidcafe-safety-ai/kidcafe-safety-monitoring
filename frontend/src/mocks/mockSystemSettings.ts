import type { SystemSettingsMockData } from "../types/systemSettings";

export const mockSystemSettings: SystemSettingsMockData = {
  operation: {
    store_name: "키즈월드",
    branch_name: "강남점",
    operation_start: "10:00",
    operation_end: "20:00",
    break_time: "14:00 ~ 14:30 정리 시간",
    max_capacity: 40,
    crowd_threshold: 30,
    default_staff_count: 4,
    guardian_notice:
      "안전 확인이 필요한 상황은 직원 확인 후 보호자에게 안내됩니다.",
  },
  alerts: {
    risk_alert_enabled: true,
    sound_enabled: true,
    popup_enabled: true,
    staff_ack_required: true,
    repeat_interval_minutes: 3,
    auto_clear_minutes: 10,
    severity_rules: [
      {
        severity: "HIGH",
        method: "팝업 + 알림음",
        staff_confirmation: "직원 확인 필수",
      },
      {
        severity: "MEDIUM",
        method: "화면 표시",
        staff_confirmation: "직원 확인 선택",
      },
      {
        severity: "LOW",
        method: "기록만 저장",
        staff_confirmation: "확인 불필요",
      },
    ],
  },
  reports: {
    daily_auto_enabled: true,
    weekly_enabled: true,
    guardian_share_enabled: true,
    generation_time: "20:30",
    included_items: [
      "이용 시간",
      "주요 이용 구역",
      "안전 알림 요약",
      "직원 확인 메모",
      "특이사항",
    ],
    guardian_share_message:
      "오늘 이용 중 확인된 안전 알림과 직원 조치 내역을 요약해 공유합니다.",
    pdf_download_enabled: true,
  },
  data_retention: {
    event_retention_days: 90,
    alert_retention_days: 90,
    report_retention_label: "1년",
    snapshot_enabled: false,
    snapshot_retention_days: 14,
    auto_delete_old_data: true,
    admin_delete_only: true,
  },
  privacy: {
    show_child_name_on_share: false,
    anonymize_child_id: true,
    save_face_image: false,
    mask_face_image: true,
    staff_review_before_share: true,
    external_link_expire_hours: 48,
    privacy_notice:
      "보호자 공유 리포트에는 운영 확인에 필요한 최소 정보만 포함합니다.",
  },
  staff_permissions: {
    staff_members: [
      { name: "김민지", role: "관리자", work_status: "근무중" },
      { name: "박서준", role: "매니저", work_status: "근무중" },
      { name: "이하나", role: "직원", work_status: "휴게" },
      { name: "최유진", role: "직원", work_status: "퇴근" },
    ],
    role_permissions: [
      {
        role: "관리자",
        alert_check: true,
        alert_resolve: true,
        report_create: true,
        report_share: true,
        zone_edit: true,
        system_setting_edit: true,
      },
      {
        role: "매니저",
        alert_check: true,
        alert_resolve: true,
        report_create: true,
        report_share: true,
        zone_edit: true,
        system_setting_edit: false,
      },
      {
        role: "직원",
        alert_check: true,
        alert_resolve: true,
        report_create: false,
        report_share: false,
        zone_edit: false,
        system_setting_edit: false,
      },
    ],
  },
};
