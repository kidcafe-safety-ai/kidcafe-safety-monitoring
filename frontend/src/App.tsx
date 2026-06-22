import { BarChart3, MapPinned, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import EventsPage from "./pages/EventsPage";
import MonitoringPage from "./pages/MonitoringPage";
import ZoneSettingsPage from "./pages/ZoneSettingsPage";

type PageKey = "monitoring" | "events" | "zone-settings";
type Theme = "light" | "dark";

const THEME_STORAGE_KEY = "kidcafe-dashboard-theme";

function getInitialTheme(): Theme {
  const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  return savedTheme === "dark" ? "dark" : "light";
}

export default function App() {
  const [page, setPage] = useState<PageKey>("monitoring");
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const isDarkMode = theme === "dark";
  const ThemeIcon = isDarkMode ? Sun : Moon;
  const ActivePage =
    page === "monitoring"
      ? MonitoringPage
      : page === "events"
        ? EventsPage
        : ZoneSettingsPage;

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
            onClick={() => setPage("monitoring")}
            type="button"
          >
            <Monitor size={18} strokeWidth={2.2} />
            <span>실시간 모니터링</span>
          </button>
          <button
            className={page === "events" ? "active" : ""}
            onClick={() => setPage("events")}
            type="button"
          >
            <BarChart3 size={18} strokeWidth={2.2} />
            <span>이벤트 기록 / 통계</span>
          </button>
          <button
            className={page === "zone-settings" ? "active" : ""}
            onClick={() => setPage("zone-settings")}
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
            <span>Phase 2</span>
            <strong>API Ready</strong>
          </div>
        </div>
      </aside>
      <div className="content">
        <ActivePage />
      </div>
    </div>
  );
}
