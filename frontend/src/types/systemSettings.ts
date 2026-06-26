export type SeverityLevel = "HIGH" | "MEDIUM" | "LOW";
export type StaffRole = "관리자" | "매니저" | "직원";

export interface StoreOperationSettings {
  store_name: string;
  branch_name: string;
  operation_start: string;
  operation_end: string;
  break_time: string;
  max_capacity: number;
  crowd_threshold: number;
  default_staff_count: number;
  guardian_notice: string;
}

export interface SeverityAlertRule {
  severity: SeverityLevel;
  method: string;
  staff_confirmation: string;
}

export interface GlobalAlertSettings {
  risk_alert_enabled: boolean;
  sound_enabled: boolean;
  popup_enabled: boolean;
  staff_ack_required: boolean;
  repeat_interval_minutes: number;
  auto_clear_minutes: number;
  severity_rules: SeverityAlertRule[];
}

export interface ReportSettings {
  daily_auto_enabled: boolean;
  weekly_enabled: boolean;
  guardian_share_enabled: boolean;
  generation_time: string;
  included_items: string[];
  guardian_share_message: string;
  pdf_download_enabled: boolean;
}

export interface DataRetentionSettings {
  event_retention_days: number;
  alert_retention_days: number;
  report_retention_label: string;
  snapshot_enabled: boolean;
  snapshot_retention_days: number;
  auto_delete_old_data: boolean;
  admin_delete_only: boolean;
}

export interface PrivacySharingSettings {
  show_child_name_on_share: boolean;
  anonymize_child_id: boolean;
  save_face_image: boolean;
  mask_face_image: boolean;
  staff_review_before_share: boolean;
  external_link_expire_hours: number;
  privacy_notice: string;
}

export interface StaffMember {
  name: string;
  role: StaffRole;
  work_status: string;
}

export interface RolePermission {
  role: StaffRole;
  alert_check: boolean;
  alert_resolve: boolean;
  report_create: boolean;
  report_share: boolean;
  zone_edit: boolean;
  system_setting_edit: boolean;
}

export interface StaffPermissionSettings {
  staff_members: StaffMember[];
  role_permissions: RolePermission[];
}

export interface SystemSettingsMockData {
  operation: StoreOperationSettings;
  alerts: GlobalAlertSettings;
  reports: ReportSettings;
  data_retention: DataRetentionSettings;
  privacy: PrivacySharingSettings;
  staff_permissions: StaffPermissionSettings;
}
