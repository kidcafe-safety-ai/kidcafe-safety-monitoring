import {
  BarChart3,
  Bell,
  FileText,
  MapPinned,
  Monitor,
  Moon,
  Settings,
  Sun,
} from "lucide-react";
import { useEffect, useState } from "react";
import SystemSettingsModal from "./components/SystemSettingsModal";
import AlertHistoryPage from "./pages/AlertHistoryPage";
import EventsPage from "./pages/EventsPage";
import MonitoringPage from "./pages/MonitoringPage";
import ReportPage from "./pages/ReportPage";
import ZoneSettingsPage from "./pages/ZoneSettingsPage";

type PageKey =
  | "monitoring"
  | "alert-history"
  | "events"
  | "report"
  | "zone-settings";
type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "kidcafe-dashboard-theme";

interface DashboardNavigationEventDetail {
  page?: PageKey;
  eventId?: string;
}

function getInitialTheme(): Theme {
  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  return savedTheme === "dark" ? "dark" : "light";
}

export default function App() {
  const [page, setPage] = useState<PageKey>("monitoring");
  const [focusedAlertEventId, setFocusedAlertEventId] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [isSystemSettingsOpen, setIsSystemSettingsOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    const handleDashboardNavigation = (event: Event) => {
      const detail = (event as CustomEvent<DashboardNavigationEventDetail>).detail;

      if (
        detail?.page === "monitoring" ||
        detail?.page === "alert-history" ||
        detail?.page === "events" ||
        detail?.page === "report" ||
        detail?.page === "zone-settings"
      ) {
        setPage(detail.page);
        setFocusedAlertEventId(
          detail.page === "alert-history" && detail.eventId ? detail.eventId : null,
        );
      }
    };

    window.addEventListener("kidcafe:navigate", handleDashboardNavigation);

    return () => {
      window.removeEventListener("kidcafe:navigate", handleDashboardNavigation);
    };
  }, []);

  const isDarkMode = theme === "dark";
  const ThemeIcon = isDarkMode ? Sun : Moon;
  const activePage =
    page === "monitoring" ? (
      <MonitoringPage />
    ) : page === "alert-history" ? (
      <AlertHistoryPage focusedEventId={focusedAlertEventId} />
    ) : page === "events" ? (
      <EventsPage />
    ) : page === "report" ? (
      <ReportPage />
    ) : (
      <ZoneSettingsPage />
    );

  const handlePageChange = (nextPage: PageKey) => {
    setPage(nextPage);
    setFocusedAlertEventId(null);
  };

  return (
    <div className="app-shell" data-theme={theme}>
      <aside className="sidebar">
        <div className="sidebar-logo-area">
          <img
            alt="KidCafe Safety Monitor"
            className="sidebar-logo-image"
            src="/kidcafe-logo.svg"
          />
        </div>
        <nav className="nav">
          <button
            className={page === "monitoring" ? "active" : ""}
            onClick={() => handlePageChange("monitoring")}
            type="button"
          >
            <Monitor size={18} strokeWidth={2.2} />
            <span>실시간 모니터링</span>
          </button>
          <button
            className={page === "alert-history" ? "active" : ""}
            onClick={() => handlePageChange("alert-history")}
            type="button"
          >
            <Bell size={18} strokeWidth={2.2} />
            <span>알림 기록</span>
          </button>
          <button
            className={page === "events" ? "active" : ""}
            onClick={() => handlePageChange("events")}
            type="button"
          >
            <BarChart3 size={18} strokeWidth={2.2} />
            <span>이벤트 기록 / 통계</span>
          </button>
          <button
            className={page === "report" ? "active" : ""}
            onClick={() => handlePageChange("report")}
            type="button"
          >
            <FileText size={18} strokeWidth={2.2} />
            <span>리포트 생성</span>
          </button>
          <button
            className={page === "zone-settings" ? "active" : ""}
            onClick={() => handlePageChange("zone-settings")}
            type="button"
          >
            <MapPinned size={18} strokeWidth={2.2} />
            <span>안전구역 / 알림 설정</span>
          </button>
        </nav>
        <div className="sidebar-footer">
          <button
            className="theme-toggle"
            onClick={() => setTheme(isDarkMode ? "light" : "dark")}
            type="button"
          >
            <ThemeIcon size={18} strokeWidth={2.2} />
            <span>{isDarkMode ? "Light Mode" : "Dark Mode"}</span>
          </button>
          <div className="sidebar-status">
            <span>v0.3.0</span>
            <strong>Stable</strong>
          </div>
        </div>
      </aside>
      <div className="content">
        <div className="content-toolbar">
          <button
            aria-label="시스템 설정 열기"
            className="settings-icon-button"
            onClick={() => setIsSystemSettingsOpen(true)}
            title="시스템 설정"
            type="button"
          >
            <Settings size={19} strokeWidth={2.2} />
          </button>
        </div>
        {activePage}
      </div>
      <SystemSettingsModal
        isOpen={isSystemSettingsOpen}
        onClose={() => setIsSystemSettingsOpen(false)}
      />
    </div>
  );
}
