/**
 * App shell — production single-screen mode with a slim left icon-rail.
 *
 * Mode is selected by URL hash so it survives reload:
 *   #/overview      → Screen 1 (Executive Summary)
 *   #/modules       → Screen 2 (Module Drill-down)
 *   #/links         → Screen 3 (Link Inspector, data state)
 *   #/links/empty   → Screen 3 empty state
 *   #/links/loading → Screen 3 loading state
 *   #/links/error   → Screen 3 error state
 *   #/anomalies     → Screen 4 (Anomaly Browser)
 *   #/export        → Screen 5 (Export & Gate Center)
 *   #/pipeline      → Screen 6 (Pipeline Run Detail)
 *
 * The hash router is intentionally tiny — Phase 4 replaces it with
 * TanStack Router or React Router once the routing surface grows past 10
 * routes.
 *
 * The all-screens "design canvas" is still available under
 * src/canvas/DesignCanvas.tsx for design review; it is not wired into the
 * running app.
 */

import React, { useEffect, useState } from "react";
import { Icon } from "./components/shared";
import type { IconName } from "./components/shared";
import { RunSelector } from "./components/RunSelector";
import { ActiveRunProvider } from "./contexts/ActiveRun";
import { AnomalyBrowser } from "./screens/AnomalyBrowser";
import { ExecSummary } from "./screens/ExecSummary";
import { ExportGate } from "./screens/ExportGate";
import { LinkInspector } from "./screens/LinkInspector";
import { ModuleDrilldown } from "./screens/ModuleDrilldown";
import { PipelineRun } from "./screens/PipelineRun";

function useHashRoute(): string {
  const [hash, setHash] = useState<string>(() =>
    typeof window === "undefined" ? "" : window.location.hash || "#/overview",
  );
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/overview");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

type Theme = "light" | "dark";

interface NavItem {
  hash: string;
  label: string;
  icon: IconName;
}

const NAV: NavItem[] = [
  { hash: "#/overview", label: "Overview", icon: "grid" },
  { hash: "#/modules", label: "Modules", icon: "layers" },
  { hash: "#/links", label: "Links", icon: "link" },
  { hash: "#/anomalies", label: "Anomalies", icon: "alert" },
  { hash: "#/export", label: "Export", icon: "download" },
  { hash: "#/pipeline", label: "Pipeline", icon: "cpu" },
];

const App: React.FC = () => {
  const hash = useHashRoute();
  const [theme, setTheme] = useState<Theme>("light");
  const toggleTheme = () => setTheme((t) => (t === "light" ? "dark" : "light"));

  // —— Single-screen routing ——————————————————————————————————————
  let screen: React.ReactNode;
  if (hash === "#/overview") screen = <ExecSummary theme={theme} />;
  else if (hash === "#/modules") screen = <ModuleDrilldown theme={theme} />;
  else if (hash === "#/links") screen = <LinkInspector theme={theme} state="data" />;
  else if (hash === "#/links/empty") screen = <LinkInspector theme={theme} state="empty" />;
  else if (hash === "#/links/loading") screen = <LinkInspector theme={theme} state="loading" />;
  else if (hash === "#/links/error") screen = <LinkInspector theme={theme} state="error" />;
  else if (hash === "#/anomalies") screen = <AnomalyBrowser theme={theme} />;
  else if (hash === "#/export") screen = <ExportGate theme={theme} />;
  else if (hash === "#/pipeline") screen = <PipelineRun theme={theme} />;
  else screen = <ExecSummary theme={theme} />;

  return (
    <ActiveRunProvider>
      <div className={`hv-shell ${theme === "dark" ? "theme-dark" : ""}`}>
        <SideRail
          active={hash}
          onSelect={(h) => (window.location.hash = h)}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
        <div className="app-main">
          <RunSelector />
          <div className="app-live">{screen}</div>
        </div>
      </div>
    </ActiveRunProvider>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// SideRail — slim, theme-aware left navigation rail.
// ─────────────────────────────────────────────────────────────────────────────

const SideRail: React.FC<{
  active: string;
  onSelect: (hash: string) => void;
  theme: Theme;
  onToggleTheme: () => void;
}> = ({ active, onSelect, theme, onToggleTheme }) => {
  // The Link Inspector state-variants (#/links/empty …) all light up "Links".
  const base = active.split("/").slice(0, 2).join("/") || "#/overview";
  return (
    <nav className="rail" aria-label="Primary">
      <div className="rail-brand" title="Hyperlink Engine · v3.4.2">
        <div className="rail-logo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
            <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
            <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
          </svg>
        </div>
      </div>

      <div className="rail-nav">
        {NAV.map((n) => {
          const isActive = base === n.hash || (n.hash === "#/overview" && (active === "" || active === "#"));
          return (
            <button
              key={n.hash}
              className={`rail-item ${isActive ? "active" : ""}`}
              onClick={() => onSelect(n.hash)}
              title={n.label}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon name={n.icon} size={18} color="currentColor" strokeWidth={isActive ? 2 : 1.6} />
              <span className="rail-label">{n.label}</span>
            </button>
          );
        })}
      </div>

      <div className="rail-foot">
        <button
          className="rail-item"
          onClick={onToggleTheme}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          <Icon name={theme === "dark" ? "sun" : "moon"} size={18} color="currentColor" strokeWidth={1.6} />
          <span className="rail-label">{theme === "dark" ? "Light" : "Dark"}</span>
        </button>
        <button className="rail-item" title="Settings">
          <Icon name="settings" size={18} color="currentColor" strokeWidth={1.6} />
          <span className="rail-label">Settings</span>
        </button>
      </div>
    </nav>
  );
};

export default App;
