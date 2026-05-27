/**
 * App shell — switches between a single-screen mode (production) and the
 * design canvas mode that mirrors the original `Hyperlink Engine.html`
 * entry by rendering all 6 artboards on one page.
 *
 * Mode is selected by URL hash so it survives reload:
 *   #/canvas        → design canvas (all screens, scaled)
 *   #/overview      → Screen 1 (Executive Summary)
 *   #/modules       → Screen 2
 *   #/links         → Screen 3 (Link Inspector, data state)
 *   #/links/empty   → Screen 3 empty state
 *   #/links/loading → Screen 3 loading state
 *   #/links/error   → Screen 3 error state
 *   #/anomalies     → Screen 4
 *   #/export        → Screen 5
 *   #/pipeline      → Screen 6
 *
 * The hash router is intentionally tiny — Phase 4 replaces it with
 * TanStack Router or React Router once the routing surface grows past 10
 * routes.
 */

import React, { useEffect, useState } from "react";
import { DesignCanvas } from "./canvas/DesignCanvas";
import { AnomalyBrowser } from "./screens/AnomalyBrowser";
import { ExecSummary } from "./screens/ExecSummary";
import { ExportGate } from "./screens/ExportGate";
import { LinkInspector } from "./screens/LinkInspector";
import type { InspectorState } from "./screens/LinkInspector";
import { ModuleDrilldown } from "./screens/ModuleDrilldown";
import { PipelineRun } from "./screens/PipelineRun";

function useHashRoute(): string {
  const [hash, setHash] = useState<string>(() =>
    typeof window === "undefined" ? "" : window.location.hash || "#/canvas",
  );
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/canvas");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

type Theme = "light" | "dark";

interface NavItem {
  hash: string;
  label: string;
}

const NAV: NavItem[] = [
  { hash: "#/canvas", label: "All screens" },
  { hash: "#/overview", label: "01 · Overview" },
  { hash: "#/modules", label: "02 · Modules" },
  { hash: "#/links", label: "03 · Links" },
  { hash: "#/anomalies", label: "04 · Anomalies" },
  { hash: "#/export", label: "05 · Export" },
  { hash: "#/pipeline", label: "06 · Pipeline" },
];

const App: React.FC = () => {
  const hash = useHashRoute();
  const [theme, setTheme] = useState<Theme>("light");
  const toggleTheme = () => setTheme((t) => (t === "light" ? "dark" : "light"));

  // —— Design canvas mode: render all 6 artboards on one page —————
  if (hash === "#/canvas" || hash === "" || hash === "#") {
    return (
      <>
        <DesignCanvasBar onSelect={(h) => (window.location.hash = h)} active={hash} />
        <DesignCanvas
          artboards={[
            { id: "s1", label: "Executive Summary", node: <ExecSummary theme="light" /> },
            { id: "s2", label: "Module Drill-down", node: <ModuleDrilldown theme="light" /> },
            { id: "s3", label: "Link Inspector", node: <LinkInspector theme="light" /> },
            { id: "s4", label: "Anomaly Browser", node: <AnomalyBrowser theme="light" /> },
            { id: "s5", label: "Export & Gate Center", node: <ExportGate theme="light" /> },
            { id: "s6", label: "Pipeline Run Detail", node: <PipelineRun theme="light" /> },
            { id: "d1", label: "Exec Summary · dark", node: <ExecSummary theme="dark" /> },
            { id: "d3", label: "Link Inspector · dark", node: <LinkInspector theme="dark" /> },
            { id: "d6", label: "Pipeline · dark", node: <PipelineRun theme="dark" /> },
            { id: "e1", label: "Link Inspector · empty", node: <LinkInspector state="empty" /> },
            { id: "e2", label: "Link Inspector · loading", node: <LinkInspector state="loading" /> },
            { id: "e3", label: "Link Inspector · error", node: <LinkInspector state="error" /> },
          ]}
        />
      </>
    );
  }

  // —— Single-screen modes ——————————————————————————————————————
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

  // The TopBar's theme toggle is wired through props on each screen for now.
  // For a production app, lift theme into a context.
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>
      <DesignCanvasBar
        onSelect={(h) => (window.location.hash = h)}
        active={hash}
        right={
          <button
            onClick={toggleTheme}
            style={{
              fontSize: 11,
              fontFamily: "'Inter', sans-serif",
              padding: "4px 10px",
              borderRadius: 4,
              border: "1px solid rgba(0,0,0,0.12)",
              background: "rgba(255,255,255,0.6)",
              color: "rgba(40,30,20,0.85)",
              cursor: "pointer",
            }}
          >
            {theme === "light" ? "Dark mode" : "Light mode"}
          </button>
        }
      />
      <div style={{ height: "calc(100vh - 36px)", overflow: "auto" }}>{screen}</div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// DesignCanvasBar — top-of-page navigator (separate from the in-screen TopBar).
// ─────────────────────────────────────────────────────────────────────────────

const DesignCanvasBar: React.FC<{
  onSelect: (hash: string) => void;
  active: string;
  right?: React.ReactNode;
}> = ({ onSelect, active, right }) => (
  <div
    style={{
      height: 36,
      padding: "0 16px",
      display: "flex",
      alignItems: "center",
      gap: 6,
      background: "#1a1a1a",
      color: "#e8e8e8",
      fontFamily: "'Inter', system-ui, sans-serif",
      fontSize: 12,
      borderBottom: "1px solid #2a2a2a",
    }}
  >
    <span
      style={{
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 10,
        color: "#888",
        letterSpacing: "0.04em",
        marginRight: 8,
      }}
    >
      hv-engine · v3.4.2
    </span>
    {NAV.map((n) => {
      const isActive = active === n.hash || (active === "" && n.hash === "#/canvas");
      return (
        <button
          key={n.hash}
          onClick={() => onSelect(n.hash)}
          style={{
            padding: "4px 10px",
            borderRadius: 4,
            border: "none",
            background: isActive ? "rgba(255,255,255,0.12)" : "transparent",
            color: isActive ? "#fff" : "#bbb",
            fontFamily: "inherit",
            fontSize: 11,
            cursor: "pointer",
            fontWeight: isActive ? 500 : 400,
          }}
        >
          {n.label}
        </button>
      );
    })}
    <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>{right}</div>
  </div>
);

export default App;
